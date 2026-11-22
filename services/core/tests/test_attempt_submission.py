"""HTTP regression tests against an isolated schema in TEST_DATABASE_URL."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from core import db, task_loader


@pytest.fixture
def harness(monkeypatch, tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    schema = "attempt_test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    dsn = make_conninfo(url, options=f"-c search_path={schema} -c statement_timeout=10000")
    monkeypatch.setattr(db, "DATABASE_URL", dsn)
    monkeypatch.setattr(task_loader, "TASKS_DIR", tmp_path)
    from core import api

    db.init_db()
    backups = []
    grades = []

    def connect():
        return psycopg.connect(dsn, row_factory=dict_row)

    def snapshot():
        with connect() as conn:
            return conn.execute("SELECT * FROM attempts WHERE id = 1").fetchone()

    def grade(seed, answers):
        grades.append(answers)
        return {"score": answers["value"], "max_score": 10, "checks": answers,
                "solution_steps": ["heavy"]}

    def backup(**kwargs):
        # A new connection must already see both result and event at backup time.
        row = snapshot()
        assert row["answers"] == kwargs["answers"]
        assert row["grading"] == kwargs["grading"]
        assert row["submitted_at"].isoformat() == kwargs["submitted_at"]
        with connect() as conn:
            assert conn.execute("SELECT count(*) AS n FROM events WHERE name = 'attempt.submit'").fetchone()["n"] == 1
        backups.append(kwargs)

    monkeypatch.setattr(api.registry, "get_generator", lambda _: SimpleNamespace(grade=grade))
    monkeypatch.setattr(api, "append_live_submission_backup", backup)

    class PausedConnection:
        """Delegate SQL to PostgreSQL; pause only after the initial SELECT executed."""
        def __init__(self, conn, gate):
            self.conn, self.gate = conn, gate

        def execute(self, sql, params=None):
            cursor = self.conn.execute(sql, params)
            if self.gate and sql.startswith("SELECT id, user_id,"):
                reached, release = self.gate
                self.gate = None
                reached.set()
                assert release.wait(10), "Concurrent request did not release SELECT"
            return cursor

        def commit(self):
            self.conn.commit()

    with connect() as conn:
        conn.execute("INSERT INTO users (key_hash) VALUES ('owner'), ('other')")
        conn.execute("INSERT INTO attempts (user_id, task_id, seed) VALUES (1, 'test', 42)")

    def request(method, value=3, user=1, gate=None, attempt_id=1):
        # Each client gets its own app to keep concurrent dependency settings isolated.
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(api.app.router)
        def connection():
            with connect() as conn:
                yield PausedConnection(conn, gate)
        app.dependency_overrides[api.get_db] = connection
        app.dependency_overrides[api.require_current_user] = lambda: (user, "test-key")
        client = TestClient(app)  # Do not run production lifespan/backup jobs.
        try:
            suffix = "answers" if method == "PATCH" else "submit"
            return client.request(method, f"/api/attempts/{attempt_id}/{suffix}", json={"answers": {"value": value}})
        finally:
            client.close()

    def events():
        with connect() as conn:
            return conn.execute("SELECT name, payload FROM events ORDER BY id").fetchall()

    try:
        yield SimpleNamespace(request=request, snapshot=snapshot, backups=backups,
                              grades=grades, events=events, connect=connect)
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def assert_accepted(h, response, value):
    assert response.status_code == 200
    body, row = response.json(), h.snapshot()
    assert body["answers"] == row["answers"] == {"value": value}
    assert body["score"] == row["score"] == value
    assert body["grading"] == row["grading"] == {"score": value, "max_score": 10, "checks": {"value": value}}
    assert body["submitted_at"] == row["submitted_at"].isoformat()
    assert len(h.backups) == 1
    assert len([e for e in h.events() if e["name"] == "attempt.submit"]) == 1


def test_draft(harness):
    h = harness
    assert h.request("PATCH").status_code == 200
    assert h.snapshot()["answers"] == {"value": 3}
    assert h.snapshot()["submitted_at"] is None
    assert [e["name"] for e in h.events()] == ["answer.save"]
    assert not h.backups


def test_submit_repeat_and_late_patch(harness):
    h = harness
    first = h.request("POST")
    assert_accepted(h, first, 3)
    before = h.snapshot()
    repeat = h.request("POST", 9)
    assert repeat.json() == first.json()
    patch = h.request("PATCH", 8)
    assert patch.status_code == 409
    assert patch.json()["detail"]["code"] == "ATTEMPT_ALREADY_SUBMITTED"
    assert h.snapshot() == before
    assert len(h.grades) == 1
    assert_accepted(h, repeat, 3)
    assert len(h.events()) == 1


@pytest.mark.parametrize("method", ["PATCH", "POST"])
def test_stale_read_loses_to_committed_submission(harness, method):
    h = harness
    reached, release = Event(), Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        loser = pool.submit(h.request, method, 9, gate=(reached, release))
        try:
            assert reached.wait(10), "Request did not reach SELECT"
            winner = h.request("POST", 4)
            assert_accepted(h, winner, 4)
            before = h.snapshot()
        finally:
            release.set()
        result = loser.result(timeout=10)
    if method == "PATCH":
        assert result.status_code == 409
        assert result.json()["detail"]["code"] == "ATTEMPT_ALREADY_SUBMITTED"
    else:
        assert result.json() == winner.json()
        assert len(h.grades) == 2
    assert h.snapshot() == before
    assert len(h.events()) == 1
    assert_accepted(h, h.request("POST", 7), 4)


@pytest.mark.parametrize("method", ["PATCH", "POST"])
@pytest.mark.parametrize("user, attempt_id, status", [(2, 1, 403), (1, 999, 404)])
def test_owner_and_missing(harness, method, user, attempt_id, status):
    h = harness
    before = h.snapshot()
    assert h.request(method, user=user, attempt_id=attempt_id).status_code == status
    assert h.snapshot() == before
    assert not h.events()
    assert not h.backups


def test_event_failure_rolls_back_submission(harness):
    h = harness
    with h.connect() as conn:
        conn.execute("ALTER TABLE events ADD CONSTRAINT reject_submit CHECK (name <> 'attempt.submit')")
    before = h.snapshot()
    with pytest.raises(psycopg.errors.CheckViolation):
        h.request("POST")
    assert h.snapshot() == before
    assert not h.events()
    assert not h.backups
