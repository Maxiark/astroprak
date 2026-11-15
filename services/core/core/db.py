import hashlib
import os
import re
import secrets
from typing import Any, Dict, Optional, Tuple

import psycopg
from psycopg.rows import dict_row

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


def get_or_create_user(conn: psycopg.Connection, raw_key: Optional[str]) -> Tuple[int, str]:
    """
    Возвращает (user_id, raw_key).
    Если передан невалидный ключ, он игнорируется и генерируется новый.
    """
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


def finalize_attempt(
    conn: psycopg.Connection,
    attempt_id: int,
    user_id: int,
    answers: Dict[str, Any],
    score: Optional[float],
    grading: Optional[Dict[str, Any]],
) -> bool:
    """Идемпотентная фиксация сдачи попытки с проверкой владельца."""
    row = conn.execute(
        """
        UPDATE attempts
        SET answers = %s,
            score = %s,
            grading = %s,
            submitted_at = COALESCE(submitted_at, NOW())
        WHERE id = %s AND user_id = %s
        RETURNING id, submitted_at
        """,
        (
            psycopg.types.json.Jsonb(answers),
            score,
            psycopg.types.json.Jsonb(grading) if grading is not None else None,
            attempt_id,
            user_id,
        ),
    ).fetchone()
    conn.commit()
    return bool(row)