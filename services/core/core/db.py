import hashlib
import logging
import os
import re
import secrets
from typing import Any, Dict, Optional, Tuple

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://astrosite_v2:astrosite@db:5432/astrosite_v2",
).replace("postgresql+psycopg://", "postgresql://")

HEX_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def get_db():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def normalize_key(key: Optional[str]) -> Optional[str]:
    """Удаляет пробелы, переводит в нижний регистр и валидирует 32 hex-символа."""
    if not key or not isinstance(key, str):
        return None
    cleaned = key.strip().lower()
    return cleaned if HEX_KEY_PATTERN.match(cleaned) else None


def hash_key(key: str) -> str:
    """Хеширует ключ строго в нижнем регистре."""
    return hashlib.sha256(key.strip().lower().encode("utf-8")).hexdigest()


def init_db():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    key_hash TEXT UNIQUE NOT NULL,
                    raw_key TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS attempts (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL,
                    seed BIGINT,
                    task_data JSONB NOT NULL DEFAULT '{}'::jsonb,
                    answers JSONB NOT NULL DEFAULT '{}'::jsonb,
                    score DOUBLE PRECISION,
                    grading JSONB,
                    submitted_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            cur.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='attempts' AND column_name='score'
                    ) THEN
                        ALTER TABLE attempts ADD COLUMN score DOUBLE PRECISION;
                        ALTER TABLE attempts ADD COLUMN grading JSONB;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='attempts' AND column_name='updated_at'
                    ) THEN
                        ALTER TABLE attempts ADD COLUMN updated_at TIMESTAMPTZ;
                    END IF;
                END $$;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id BIGSERIAL PRIMARY KEY,
                    attempt_id BIGINT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS session_transfers (
                    token TEXT PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    target_path TEXT NOT NULL DEFAULT '/',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                );
            """)

            # Индексы для быстрого поиска по участнику, пагинации и выгрузки логов
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_raw_key ON users (raw_key);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_attempts_created_at ON attempts (created_at DESC, id DESC);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_attempts_user_task ON attempts (user_id, task_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_events_attempt_id ON events (attempt_id, created_at ASC);")
        conn.commit()


def get_db_size_info(conn: psycopg.Connection) -> Dict[str, Any]:
    """Возвращает текущий размер базы данных, таблиц attempts/events и число раздутых записей."""
    row = conn.execute(
        """
        SELECT
            pg_database_size(current_database()) AS db_bytes,
            pg_total_relation_size('attempts') AS attempts_bytes,
            pg_total_relation_size('events') AS events_bytes,
            (SELECT COUNT(*) FROM attempts) AS total_attempts,
            (SELECT COUNT(*) FROM attempts WHERE task_data <> '{}'::jsonb) AS bloated_task_data_count
        """
    ).fetchone()
    if not row:
        return {"db_mb": 0.0, "attempts_mb": 0.0, "events_mb": 0.0, "total_attempts": 0, "bloated_count": 0}
    return {
        "db_mb": round(float(row["db_bytes"]) / (1024 * 1024), 2),
        "attempts_mb": round(float(row["attempts_bytes"]) / (1024 * 1024), 2),
        "events_mb": round(float(row["events_bytes"]) / (1024 * 1024), 2),
        "total_attempts": int(row["total_attempts"]),
        "bloated_count": int(row["bloated_task_data_count"]),
    }


def compact_database(delete_short_attempts: bool = False) -> Dict[str, Any]:
    """
    Освобождает гигабайты дискового пространства PostgreSQL:
    1) Очищает дублирующийся JSONB `task_data` (где хранились base64-картинки по 500 КБ на каждую попытку)
       и тяжёлые base64-картинки `solution_assets` внутри `grading`, так как задача всегда восстанавливается по `(task_id, seed)`.
    2) Опционально удаляет пустые/короткие попытки (< 5 с).
    3) Выполняет `VACUUM FULL ANALYZE` в режиме autocommit для физического возврата гигабайтов диску ОС.
    """
    deleted_short = 0
    cleaned_bloat = 0

    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        before_info = get_db_size_info(conn)
        with conn.cursor() as cur:
            if delete_short_attempts:
                cur.execute(
                    """
                    DELETE FROM attempts a
                    WHERE GREATEST(
                        0,
                        EXTRACT(
                            EPOCH FROM (
                                GREATEST(
                                    a.created_at,
                                    COALESCE(a.submitted_at, a.created_at),
                                    COALESCE(a.updated_at, a.created_at),
                                    COALESCE((SELECT MAX(e.created_at) FROM events e WHERE e.attempt_id = a.id), a.created_at)
                                ) - a.created_at
                            )
                        )::int
                    ) < 5
                    """
                )
                deleted_short = cur.rowcount or 0

            cur.execute(
                """
                UPDATE attempts
                SET task_data = '{}'::jsonb
                WHERE task_data <> '{}'::jsonb
                """
            )
            cleaned_bloat = cur.rowcount or 0

            cur.execute(
                """
                UPDATE attempts
                SET grading = grading - 'solution_assets' - 'solution_steps' - 'solution_results'
                WHERE grading IS NOT NULL
                  AND (grading ? 'solution_assets' OR grading ? 'solution_steps')
                """
            )
        conn.commit()

    # VACUUM FULL требует отдельного соединения с autocommit=True
    with psycopg.connect(DATABASE_URL, autocommit=True, row_factory=dict_row) as vac_conn:
        vac_conn.execute("VACUUM FULL ANALYZE attempts;")
        vac_conn.execute("VACUUM FULL ANALYZE events;")
        vac_conn.execute("VACUUM FULL ANALYZE users;")
        after_info = get_db_size_info(vac_conn)

    return {
        "before_mb": before_info["db_mb"],
        "after_mb": after_info["db_mb"],
        "freed_mb": round(max(0.0, before_info["db_mb"] - after_info["db_mb"]), 2),
        "cleaned_bloat_rows": cleaned_bloat,
        "deleted_short_rows": deleted_short,
        "size_info": after_info,
    }


def get_or_create_user(conn: psycopg.Connection, raw_key: Optional[str]) -> Tuple[int, str]:
    clean_key = normalize_key(raw_key)
    if clean_key:
        h = hash_key(clean_key)
        row = conn.execute("SELECT id, raw_key FROM users WHERE key_hash = %s", (h,)).fetchone()
        if row:
            if row["raw_key"] != clean_key:
                conn.execute("UPDATE users SET raw_key = %s WHERE id = %s", (clean_key, row["id"]))
                conn.commit()
            return row["id"], clean_key

    new_raw = secrets.token_hex(16).lower()
    new_h = hash_key(new_raw)
    row = conn.execute(
        "INSERT INTO users (key_hash, raw_key) VALUES (%s, %s) RETURNING id",
        (new_h, new_raw),
    ).fetchone()
    conn.commit()
    return row["id"], new_raw


def strip_heavy_grading_fields(grading: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Убирает многомегабайтные base64-картинки разбора перед записью в PostgreSQL."""
    if not isinstance(grading, dict):
        return grading
    light = dict(grading)
    light.pop("solution_assets", None)
    light.pop("solution_steps", None)
    light.pop("solution_results", None)
    return light


def finalize_attempt(
    conn: psycopg.Connection,
    attempt_id: int,
    user_id: int,
    answers: Dict[str, Any],
    score: Optional[float],
    grading: Optional[Dict[str, Any]],
) -> bool:
    """Идемпотентная фиксация сдачи попытки с проверкой владельца (без сохранения тяжёлых картинок в БД)."""
    light_grading = strip_heavy_grading_fields(grading)
    row = conn.execute(
        """
        UPDATE attempts
        SET answers = %s,
            score = %s,
            grading = %s,
            updated_at = NOW(),
            submitted_at = COALESCE(submitted_at, NOW())
        WHERE id = %s AND user_id = %s
        RETURNING id, submitted_at
        """,
        (
            psycopg.types.json.Jsonb(answers),
            score,
            psycopg.types.json.Jsonb(light_grading) if light_grading is not None else None,
            attempt_id,
            user_id,
        ),
    ).fetchone()
    conn.commit()
    return bool(row)