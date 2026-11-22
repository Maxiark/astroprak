"""Progress HTTP tests use real PostgreSQL and the production auth dependency."""
import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from core import db, task_loader


@pytest.fixture
def progress(monkeypatch, tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    schema = "progress_test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    dsn = make_conninfo(url, options=f"-c search_path={schema}")
    monkeypatch.setattr(db, "DATABASE_URL", dsn)
    monkeypatch.setattr(task_loader, "TASKS_DIR", tmp_path)
    from core import api
    db.init_db()
    manifests = [
        {"id": "a", "kind": "generated"}, {"id": "b", "kind": "archive"},
        {"id": "legacy"}, {"id": "hidden", "hidden": True},
        {"id": "theory", "kind": "theory"}, {"id": "material", "kind": "material"},
    ]
    monkeypatch.setattr(api.registry, "manifests", {m["id"]: m for m in manifests})

    def forbidden(*args, **kwargs):
        pytest.fail("Progress must not generate, grade, or create users")

    monkeypatch.setattr(api.registry, "get_generator", forbidden)
    monkeypatch.setattr(api, "get_or_create_user", forbidden)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        for user_id in (1, 2):
            key = str(user_id) * 32
            conn.execute("INSERT INTO users (id, key_hash, raw_key) VALUES (%s, %s, %s)",
                         (user_id, db.hash_key(key), key))
    client = TestClient(api.app)
    client.cookies.set("astrosite_key", "1" * 32)
    try:
        yield client, dsn, api
    finally:
        client.close()
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def seed(dsn, rows):
    with psycopg.connect(dsn) as conn:
        for task, score, submitted, user in rows:
            conn.execute("""INSERT INTO attempts (task_id, score, submitted_at, user_id)
                         VALUES (%s, %s, CASE WHEN %s THEN NOW() END, %s)""",
                         (task, score, submitted, user))


@pytest.mark.parametrize("rows,solved,total,status", [
    ([], 0, 0, None),
    ([("a", 9, False, 1)], 0, 0, None),
    ([("a", 0, True, 1)], 1, 0, "solved"),
    ([("a", s, True, 1) for s in (3, 8, 5)], 1, 8, "solved"),
    ([("a", 8, True, 1), ("b", 4.5, True, 1)], 2, 12.5, "solved"),
    ([("a", None, True, 1)], 0, 0, "submitted_ungraded"),
    ([("a", 8, True, 1), ("a", 10, False, 1)], 1, 8, "solved"),
    ([("a", 8, True, 1), ("a", None, True, 1)], 1, 8, "solved"),
    ([(t, 9, True, 1) for t in ("hidden", "deleted", "theory", "material")], 0, 0, None),
    ([("a", 8, True, 2)], 0, 0, None),
    ([("a", 0.1, True, 1), ("b", 0.2, True, 1)], 2, 0.3, "solved"),
    ([("a", float('nan'), True, 1)], 0, 0, "submitted_ungraded"),
])
def test_summary(progress, rows, solved, total, status):
    client, dsn, _ = progress
    seed(dsn, rows)
    with psycopg.connect(dsn) as conn:
        before = conn.execute("SELECT row_to_json(attempts)::text FROM attempts ORDER BY id").fetchall()
    response = client.get('/api/me/progress?user_id=2&key=' + '2' * 32)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    body = response.json()
    assert body['user_id'] == 1
    assert body['summary'] == dict(solved_tasks=solved, available_tasks=3, total_score=total)
    assert body['tasks'].get('a', {}).get('status') == status
    assert set(body) == {'user_id', 'summary', 'tasks'}
    for task in body['tasks'].values():
        assert set(task) == {'status', 'best_score'}
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT row_to_json(attempts)::text FROM attempts ORDER BY id").fetchall() == before


@pytest.mark.parametrize('cookie', [None, 'invalid', '3' * 32])
def test_requires_existing_session(progress, cookie):
    client, dsn, _ = progress
    client.cookies.clear()
    if cookie:
        client.cookies.set('astrosite_key', cookie)
    response = client.get('/api/me/progress?key=' + '1' * 32)
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'no-store'
    assert 'set-cookie' not in response.headers
    with psycopg.connect(dsn) as conn:
        assert conn.execute('SELECT count(*) FROM users').fetchone()[0] == 2


def test_switch_and_empty_catalogue(progress, monkeypatch):
    client, dsn, api = progress
    seed(dsn, [('a', 8, True, 1), ('b', 4.5, True, 2)])
    for user, score in [(1, 8), (2, 4.5), (1, 8)]:
        client.cookies.set('astrosite_key', str(user) * 32)
        body = client.get('/api/me/progress').json()
        assert body['user_id'] == user
        assert body['summary']['total_score'] == score
    monkeypatch.setattr(api.registry, 'manifests', {})
    body = client.get('/api/me/progress').json()
    assert body['summary'] == dict(solved_tasks=0, available_tasks=0, total_score=0)
    assert body['tasks'] == {}
