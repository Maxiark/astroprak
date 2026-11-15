import asyncio
import csv
import io
import json
import logging
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import psycopg
from psycopg.rows import dict_row

from core.db import DATABASE_URL, hash_key
from core.task_loader import TASKS_DIR

logger = logging.getLogger(__name__)

PRIMARY_BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/app/data/backups"))
MIRROR_BACKUP_DIR = TASKS_DIR / "_backups"
BACKUP_INTERVAL_MINUTES = max(5, int(os.getenv("BACKUP_INTERVAL_MINUTES", "30")))
MAX_PERIODIC_BACKUPS = int(os.getenv("BACKUP_KEEP_COUNT", "48"))
MAX_DAILY_BACKUPS = int(os.getenv("BACKUP_KEEP_DAILY_COUNT", "30"))

_backup_state: Dict[str, Any] = {
    "last_backup_at": None,
    "last_backup_file": None,
    "last_error": None,
    "total_attempts": 0,
    "submitted_attempts": 0,
}


def get_backup_dirs() -> tuple[Path, Path]:
    """Гарантирует наличие основной директории бэкапов и зеркала внутри тома задач."""
    PRIMARY_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    MIRROR_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return PRIMARY_BACKUP_DIR, MIRROR_BACKUP_DIR


def append_live_submission_backup(
    attempt_id: int,
    user_id: int,
    student_key: str,
    task_id: str,
    seed: Optional[int],
    score: Optional[float],
    max_score: Optional[float],
    answers: Dict[str, Any],
    grading: Optional[Dict[str, Any]],
    submitted_at: str,
) -> None:
    """
    Мгновенно дописывает сданную работу в append-only журнал на диске (CSV + JSONL),
    чтобы даже при внезапном падении БД ни одна сданная работа не пропала.
    """
    try:
        primary_dir, mirror_dir = get_backup_dirs()
        record = {
            "attempt_id": attempt_id,
            "user_id": user_id,
            "student_key": student_key,
            "task_id": task_id,
            "seed": seed,
            "score": score,
            "max_score": max_score,
            "answers": answers,
            "grading": grading,
            "submitted_at": submitted_at,
        }
        jsonl_line = json.dumps(record, ensure_ascii=False) + "\n"

        csv_row = [
            attempt_id,
            student_key,
            task_id,
            seed if seed is not None else "",
            score if score is not None else "",
            max_score if max_score is not None else "",
            submitted_at,
            json.dumps(answers, ensure_ascii=False),
            json.dumps(grading, ensure_ascii=False) if grading else "",
        ]
        csv_header = [
            "ID Попытки",
            "Код участника",
            "Задача",
            "Seed",
            "Балл",
            "Макс. балл",
            "Дата сдачи (UTC)",
            "Ответы (JSON)",
            "Протокол проверки (JSON)",
        ]

        for target_dir in (primary_dir, mirror_dir):
            jsonl_path = target_dir / "submitted_live_log.jsonl"
            with open(jsonl_path, "a", encoding="utf-8") as jf:
                jf.write(jsonl_line)

            csv_path = target_dir / "submitted_live_log.csv"
            write_header = not csv_path.exists() or csv_path.stat().st_size == 0
            with open(csv_path, "a", encoding="utf-8", newline="") as cf:
                if write_header:
                    cf.write("\ufeff")
                writer = csv.writer(cf, delimiter=";")
                if write_header:
                    writer.writerow(csv_header)
                writer.writerow(csv_row)
    except Exception as e:
        logger.error("Ошибка записи live-бэкапа сдачи попытки #%s: %s", attempt_id, e)


def create_full_backup(conn: Optional[psycopg.Connection] = None, reason: str = "scheduled") -> Dict[str, Any]:
    """
    Формирует полный бэкап таблиц users, attempts и events:
    - attempts_with_codes.csv (ведомость всех попыток с кодами участников и логом действий)
    - events_log.csv (хронологический лог всех действий по всем работам)
    - full_restore_dump.json (полный дамп для автоматического восстановления БД)
    Упаковывает их в датированный ZIP-архив и обновляет latest_backup.zip.
    """
    own_conn = False
    if conn is None:
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        own_conn = True

    try:
        primary_dir, mirror_dir = get_backup_dirs()
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%d_%H-%M-%S")
        day_str = now_utc.strftime("%Y-%m-%d")

        users_rows = conn.execute(
            "SELECT id, key_hash, raw_key, created_at FROM users ORDER BY id ASC"
        ).fetchall()

        attempts_rows = conn.execute(
            """
            SELECT
                a.id AS attempt_id,
                a.user_id,
                u.raw_key AS student_key,
                a.task_id,
                a.seed,
                a.task_data,
                a.answers,
                a.score,
                a.grading,
                a.submitted_at,
                a.created_at,
                GREATEST(
                    0,
                    EXTRACT(
                        EPOCH FROM (
                            COALESCE(a.submitted_at, MAX(e.created_at), a.created_at)
                            - LEAST(a.created_at, COALESCE(MIN(e.created_at), a.created_at))
                        )
                    )::int
                ) AS duration_sec
            FROM attempts a
            JOIN users u ON u.id = a.user_id
            LEFT JOIN events e ON e.attempt_id = a.id
            GROUP BY a.id, u.raw_key
            ORDER BY a.id ASC
            """
        ).fetchall()

        events_rows = conn.execute(
            """
            SELECT
                e.id AS event_id,
                e.attempt_id,
                u.raw_key AS student_key,
                a.task_id,
                e.name,
                e.payload,
                e.created_at
            FROM events e
            JOIN attempts a ON a.id = e.attempt_id
            JOIN users u ON u.id = a.user_id
            ORDER BY e.id ASC
            """
        ).fetchall()

        events_by_attempt: Dict[int, list[dict[str, Any]]] = {}
        for ev in events_rows:
            events_by_attempt.setdefault(ev["attempt_id"], []).append({
                "id": ev["event_id"],
                "name": ev["name"],
                "payload": ev["payload"],
                "created_at": ev["created_at"].isoformat() if ev["created_at"] else None,
            })

        # 1. Формируем CSV попыток
        attempts_csv_buf = io.StringIO()
        attempts_csv_buf.write("\ufeff")
        awriter = csv.writer(attempts_csv_buf, delimiter=";")
        awriter.writerow([
            "ID Попытки",
            "Код участника",
            "Задача",
            "Seed",
            "Балл",
            "Сдано",
            "Длительность (с)",
            "Кол-во действий",
            "Дата сдачи",
            "Дата создания",
            "Ответы (JSON)",
            "Протокол проверки (JSON)",
            "Лог действий (JSON)",
        ])
        submitted_cnt = 0
        for r in attempts_rows:
            if r["submitted_at"] is not None:
                submitted_cnt += 1
            att_events = events_by_attempt.get(r["attempt_id"], [])
            awriter.writerow([
                r["attempt_id"],
                r["student_key"] or "",
                r["task_id"],
                r["seed"] if r["seed"] is not None else "",
                r["score"] if r["score"] is not None else "",
                "Да" if r["submitted_at"] else "Нет",
                r["duration_sec"] or 0,
                len(att_events),
                r["submitted_at"].strftime("%Y-%m-%d %H:%M:%S") if r["submitted_at"] else "",
                r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r["created_at"] else "",
                json.dumps(r["answers"] or {}, ensure_ascii=False),
                json.dumps(r["grading"], ensure_ascii=False) if r["grading"] else "",
                json.dumps(att_events, ensure_ascii=False),
            ])

        # 2. Формируем CSV всех действий
        events_csv_buf = io.StringIO()
        events_csv_buf.write("\ufeff")
        ewriter = csv.writer(events_csv_buf, delimiter=";")
        ewriter.writerow([
            "ID События",
            "ID Попытки",
            "Код участника",
            "Задача",
            "Время события",
            "Действие (name)",
            "Данные (payload JSON)",
        ])
        for ev in events_rows:
            ewriter.writerow([
                ev["event_id"],
                ev["attempt_id"],
                ev["student_key"] or "",
                ev["task_id"],
                ev["created_at"].strftime("%Y-%m-%d %H:%M:%S") if ev["created_at"] else "",
                ev["name"],
                json.dumps(ev["payload"] or {}, ensure_ascii=False),
            ])

        # 3. Полный JSON-дамп для восстановления
        dump_obj = {
            "version": "2.0",
            "created_at": now_utc.isoformat(),
            "reason": reason,
            "stats": {
                "users_count": len(users_rows),
                "attempts_count": len(attempts_rows),
                "submitted_count": submitted_cnt,
                "events_count": len(events_rows),
            },
            "users": [
                {
                    "id": u["id"],
                    "key_hash": u["key_hash"],
                    "raw_key": u["raw_key"],
                    "created_at": u["created_at"].isoformat() if u["created_at"] else None,
                }
                for u in users_rows
            ],
            "attempts": [
                {
                    "id": a["attempt_id"],
                    "user_id": a["user_id"],
                    "student_key": a["student_key"],
                    "task_id": a["task_id"],
                    "seed": a["seed"],
                    "task_data": a["task_data"],
                    "answers": a["answers"],
                    "score": a["score"],
                    "grading": a["grading"],
                    "duration_sec": a["duration_sec"],
                    "submitted_at": a["submitted_at"].isoformat() if a["submitted_at"] else None,
                    "created_at": a["created_at"].isoformat() if a["created_at"] else None,
                    "events": events_by_attempt.get(a["attempt_id"], []),
                }
                for a in attempts_rows
            ],
        }
        dump_json_bytes = json.dumps(dump_obj, ensure_ascii=False, indent=2).encode("utf-8")
        attempts_csv_bytes = attempts_csv_buf.getvalue().encode("utf-8")
        events_csv_bytes = events_csv_buf.getvalue().encode("utf-8")

        archive_name = f"backup_{ts_str}.zip"
        archive_path = primary_dir / archive_name

        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("attempts_with_codes.csv", attempts_csv_bytes)
            zf.writestr("events_log.csv", events_csv_bytes)
            zf.writestr("full_restore_dump.json", dump_json_bytes)

        # Обновляем latest_backup.zip и attempts_latest.csv в обеих папках
        for target_dir in (primary_dir, mirror_dir):
            shutil.copy2(archive_path, target_dir / "latest_backup.zip")
            (target_dir / "attempts_latest.csv").write_bytes(attempts_csv_bytes)

        # Ежедневный снимок
        daily_path = primary_dir / f"backup_daily_{day_str}.zip"
        if not daily_path.exists():
            shutil.copy2(archive_path, daily_path)

        _rotate_old_backups(primary_dir)

        _backup_state["last_backup_at"] = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
        _backup_state["last_backup_file"] = archive_name
        _backup_state["last_error"] = None
        _backup_state["total_attempts"] = len(attempts_rows)
        _backup_state["submitted_attempts"] = submitted_cnt

        logger.info(
            "Бэкап попыток создан: %s (попыток: %d, сдано: %d, событий: %d)",
            archive_name,
            len(attempts_rows),
            submitted_cnt,
            len(events_rows),
        )
        return {
            "status": "ok",
            "filename": archive_name,
            "created_at": _backup_state["last_backup_at"],
            "total_attempts": len(attempts_rows),
            "submitted_attempts": submitted_cnt,
            "events_count": len(events_rows),
        }
    except Exception as e:
        _backup_state["last_error"] = str(e)
        logger.error("Ошибка создания регулярного бэкапа: %s", e, exc_info=True)
        raise
    finally:
        if own_conn:
            conn.close()


def _rotate_old_backups(backup_dir: Path) -> None:
    """Удаляет устаревшие периодические и ежедневные архивы сверх установленного лимита."""
    periodic = sorted(
        [p for p in backup_dir.glob("backup_2*.zip") if not p.name.startswith("backup_daily_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_p in periodic[MAX_PERIODIC_BACKUPS:]:
        try:
            old_p.unlink()
        except Exception:
            pass

    daily = sorted(
        list(backup_dir.glob("backup_daily_*.zip")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_d in daily[MAX_DAILY_BACKUPS:]:
        try:
            old_d.unlink()
        except Exception:
            pass


def list_backups_info() -> Dict[str, Any]:
    """Возвращает статус подсистемы бэкапов и список доступных файлов."""
    primary_dir, _ = get_backup_dirs()
    files = []
    for f in sorted(primary_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix in (".zip", ".csv", ".jsonl", ".json"):
            st = f.stat()
            files.append({
                "filename": f.name,
                "size_kb": round(st.st_size / 1024.0, 1),
                "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            })
    return {
        "interval_minutes": BACKUP_INTERVAL_MINUTES,
        "last_backup_at": _backup_state["last_backup_at"],
        "last_backup_file": _backup_state["last_backup_file"],
        "last_error": _backup_state["last_error"],
        "total_attempts": _backup_state["total_attempts"],
        "submitted_attempts": _backup_state["submitted_attempts"],
        "files": files,
    }


def restore_from_dump_bytes(conn: psycopg.Connection, raw_bytes: bytes, filename: str) -> Dict[str, int]:
    """
    Восстанавливает таблицы users, attempts и events из архива backup_*.zip или файла full_restore_dump.json.
    Безопасно (идемпотентно) объединяет данные с текущей базой.
    """
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw_bytes), mode="r") as zf:
            if "full_restore_dump.json" not in zf.namelist():
                raise ValueError("В ZIP-архиве отсутствует файл full_restore_dump.json")
            dump_data = json.loads(zf.read("full_restore_dump.json").decode("utf-8"))
    else:
        dump_data = json.loads(raw_bytes.decode("utf-8"))

    users_list = dump_data.get("users", [])
    attempts_list = dump_data.get("attempts", [])

    restored_users = 0
    restored_attempts = 0
    restored_events = 0

    with conn.cursor() as cur:
        for u in users_list:
            raw_k = u.get("raw_key")
            k_hash = u.get("key_hash") or (hash_key(raw_k) if raw_k else None)
            if not k_hash:
                continue
            cur.execute(
                """
                INSERT INTO users (id, key_hash, raw_key, created_at)
                VALUES (%s, %s, %s, COALESCE(%s::timestamptz, NOW()))
                ON CONFLICT (id) DO UPDATE SET
                    raw_key = COALESCE(users.raw_key, EXCLUDED.raw_key)
                """,
                (u["id"], k_hash, raw_k, u.get("created_at")),
            )
            restored_users += 1

        for a in attempts_list:
            student_key = a.get("student_key")
            user_id = a.get("user_id")
            if student_key:
                kh = hash_key(student_key)
                urow = cur.execute("SELECT id FROM users WHERE key_hash = %s", (kh,)).fetchone()
                if urow:
                    user_id = urow["id"]
                elif user_id:
                    cur.execute(
                        """
                        INSERT INTO users (id, key_hash, raw_key)
                        VALUES (%s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (user_id, kh, student_key),
                    )

            cur.execute(
                """
                INSERT INTO attempts (
                    id, user_id, task_id, seed, task_data, answers, score, grading, submitted_at, created_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz, COALESCE(%s::timestamptz, NOW())
                )
                ON CONFLICT (id) DO UPDATE SET
                    answers = EXCLUDED.answers,
                    score = COALESCE(EXCLUDED.score, attempts.score),
                    grading = COALESCE(EXCLUDED.grading, attempts.grading),
                    submitted_at = COALESCE(attempts.submitted_at, EXCLUDED.submitted_at)
                """,
                (
                    a["id"],
                    user_id,
                    a["task_id"],
                    a.get("seed"),
                    psycopg.types.json.Jsonb(a.get("task_data") or {}),
                    psycopg.types.json.Jsonb(a.get("answers") or {}),
                    a.get("score"),
                    psycopg.types.json.Jsonb(a["grading"]) if a.get("grading") is not None else None,
                    a.get("submitted_at"),
                    a.get("created_at"),
                ),
            )
            restored_attempts += 1

            for ev in a.get("events", []):
                if ev.get("id"):
                    cur.execute(
                        """
                        INSERT INTO events (id, attempt_id, name, payload, created_at)
                        VALUES (%s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()))
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            ev["id"],
                            a["id"],
                            ev.get("name", "unknown"),
                            psycopg.types.json.Jsonb(ev.get("payload") or {}),
                            ev.get("created_at"),
                        ),
                    )
                    restored_events += 1

        # Синхронизируем последовательности BIGSERIAL после вставки явных ID
        cur.execute("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 1));")
        cur.execute("SELECT setval(pg_get_serial_sequence('attempts', 'id'), COALESCE((SELECT MAX(id) FROM attempts), 1));")
        cur.execute("SELECT setval(pg_get_serial_sequence('events', 'id'), COALESCE((SELECT MAX(id) FROM events), 1));")

    conn.commit()
    return {
        "restored_users": restored_users,
        "restored_attempts": restored_attempts,
        "restored_events": restored_events,
    }


async def periodic_backup_loop() -> None:
    """Фоновый цикл регулярного резервного копирования таблицы попыток."""
    await asyncio.sleep(3)
    while True:
        try:
            await asyncio.to_thread(create_full_backup, None, "periodic")
        except Exception as e:
            logger.error("Сбой в фоновом цикле бэкапа: %s", e)
        await asyncio.sleep(BACKUP_INTERVAL_MINUTES * 60)
