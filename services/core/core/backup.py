import asyncio
import csv
import io
import json
import logging
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.rows import dict_row

from core.db import DATABASE_URL, hash_key
from core.task_loader import TASKS_DIR

logger = logging.getLogger(__name__)

PRIMARY_BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/app/data/backups"))
MIRROR_BACKUP_DIR = TASKS_DIR / "_backups"
SETTINGS_FILE = PRIMARY_BACKUP_DIR / "backup_settings.json"

BACKUP_TYPES_META = {
    "solutions": {
        "id": "solutions",
        "title": "Компактный бэкап решений (ZIP: CSV + JSON восстановления)",
        "description": (
            "Сохраняет только сданные работы и попытки с непустыми ответами (с кодами участников, баллами, "
            "ответами и протоколами), без пустых заходов <5 с и без тяжёлых картинок. Весит десятки КБ."
        ),
    },
    "csv_only": {
        "id": "csv_only",
        "title": "Ведомость всех попыток (только таблица CSV для Excel)",
        "description": (
            "Лёгкая сводная таблица CSV со всеми попытками, кодами участников, баллами, временем и ответами "
            "(без логов событий и дампов задач)."
        ),
    },
    "full": {
        "id": "full",
        "title": "Полный системный архив (ZIP: все попытки + логи действий + дамп БД)",
        "description": (
            "Полный снимок всех таблиц (users, attempts, events) и JSON-дамп для полного восстановления базы."
        ),
    },
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "interval_minutes": max(0, int(os.getenv("BACKUP_INTERVAL_MINUTES", "360"))),
    "auto_backup_type": "solutions",
    "keep_count": max(1, int(os.getenv("BACKUP_KEEP_COUNT", "10"))),
    "keep_daily_count": max(1, int(os.getenv("BACKUP_KEEP_DAILY_COUNT", "7"))),
    "gdrive_enabled": False,
    "gdrive_folder_id": "",
    "gdrive_keep_count": 10,
    "gdrive_client_id": "",
    "gdrive_client_secret": "",
    "gdrive_refresh_token": "",
    "tg_bot_token": "",
    "tg_chat_id": "",
    "tg_topic_id": "",
}

_backup_state: Dict[str, Any] = {
    "last_backup_at": None,
    "last_backup_file": None,
    "last_backup_type": None,
    "last_gdrive_sync_at": None,
    "last_gdrive_status": None,
    "last_tg_send_at": None,
    "last_error": None,
    "total_attempts": 0,
    "submitted_attempts": 0,
}


def get_backup_dirs() -> tuple[Path, Path]:
    PRIMARY_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    MIRROR_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return PRIMARY_BACKUP_DIR, MIRROR_BACKUP_DIR


def load_backup_settings() -> Dict[str, Any]:
    get_backup_dirs()
    cfg = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.is_file():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                cfg.update(saved)
        except Exception as e:
            logger.warning("Не удалось прочитать backup_settings.json: %s", e)
    return cfg


def save_backup_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_backup_settings()
    for k in DEFAULT_SETTINGS:
        if k in updates and updates[k] is not None:
            if isinstance(DEFAULT_SETTINGS[k], bool):
                cfg[k] = bool(updates[k])
            elif isinstance(DEFAULT_SETTINGS[k], int):
                cfg[k] = max(0, int(updates[k]))
            else:
                cfg[k] = str(updates[k]).strip()
    if cfg["auto_backup_type"] not in BACKUP_TYPES_META:
        cfg["auto_backup_type"] = "solutions"
    SETTINGS_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


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
    """Мгновенно дописывает сданную работу в append-only журнал на диске (CSV + JSONL)."""
    try:
        primary_dir, mirror_dir = get_backup_dirs()
        light_grading = None
        if isinstance(grading, dict):
            light_grading = {
                k: v for k, v in grading.items()
                if k not in ("solution_assets", "solution_steps", "solution_results")
            }
        record = {
            "attempt_id": attempt_id,
            "user_id": user_id,
            "student_key": student_key,
            "task_id": task_id,
            "seed": seed,
            "score": score,
            "max_score": max_score,
            "answers": answers,
            "grading": light_grading,
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
            json.dumps(light_grading, ensure_ascii=False) if light_grading else "",
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


def _copy_query_to_csv_bytes(conn: psycopg.Connection, select_sql: str) -> bytes:
    """Быстрая выгрузка результата SQL-запроса в CSV с UTF-8 BOM через нативный PostgreSQL COPY."""
    buf = io.BytesIO()
    buf.write(b"\xef\xbb\xbf")
    copy_sql = f"COPY ({select_sql}) TO STDOUT WITH (FORMAT CSV, HEADER, DELIMITER ';')"
    with conn.cursor() as cur:
        with cur.copy(copy_sql) as copy:
            for chunk in copy:
                buf.write(bytes(chunk))
    return buf.getvalue()


def _build_restore_dump_bytes(conn: psycopg.Connection, now_utc: datetime, reason: str, only_meaningful: bool = True) -> tuple[bytes, int, int]:
    where_clause = "WHERE a.submitted_at IS NOT NULL OR a.answers <> '{}'::jsonb" if only_meaningful else ""
    users_rows = conn.execute(
        f"""
        SELECT DISTINCT u.id, u.key_hash, u.raw_key, u.created_at
        FROM users u
        JOIN attempts a ON a.user_id = u.id
        {where_clause}
        ORDER BY u.id ASC
        """
    ).fetchall()

    attempts_rows = conn.execute(
        f"""
        SELECT
            a.id,
            a.user_id,
            u.raw_key AS student_key,
            a.task_id,
            a.seed,
            a.answers,
            a.score,
            a.grading,
            a.submitted_at,
            a.created_at
        FROM attempts a
        JOIN users u ON u.id = a.user_id
        {where_clause}
        ORDER BY a.id ASC
        """
    ).fetchall()

    submitted_cnt = sum(1 for a in attempts_rows if a["submitted_at"] is not None)
    dump_obj = {
        "version": "2.2",
        "created_at": now_utc.isoformat(),
        "reason": reason,
        "only_meaningful": only_meaningful,
        "stats": {
            "users_count": len(users_rows),
            "attempts_count": len(attempts_rows),
            "submitted_count": submitted_cnt,
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
                "id": a["id"],
                "user_id": a["user_id"],
                "student_key": a["student_key"],
                "task_id": a["task_id"],
                "seed": a["seed"],
                "answers": a["answers"],
                "score": a["score"],
                "grading": a["grading"],
                "submitted_at": a["submitted_at"].isoformat() if a["submitted_at"] else None,
                "created_at": a["created_at"].isoformat() if a["created_at"] else None,
            }
            for a in attempts_rows
        ],
    }
    return json.dumps(dump_obj, ensure_ascii=False, indent=2).encode("utf-8"), len(attempts_rows), submitted_cnt


def create_backup(
    conn: Optional[psycopg.Connection] = None,
    backup_type: str = "solutions",
    reason: str = "manual",
    sync_gdrive: bool = False,
) -> Dict[str, Any]:
    """
    Создаёт резервную копию выбранного типа:
    - 'solutions': компактный ZIP (только сданные и непустые попытки: CSV + JSON восстановления)
    - 'csv_only': сводная CSV-таблица всех попыток для Excel
    - 'full': полный системный ZIP (все попытки CSV + события CSV + JSON восстановления)
    """
    if backup_type not in BACKUP_TYPES_META:
        backup_type = "solutions"

    own_conn = False
    if conn is None:
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        own_conn = True

    try:
        primary_dir, mirror_dir = get_backup_dirs()
        cfg = load_backup_settings()
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%d_%H-%M-%S")
        day_str = now_utc.strftime("%Y-%m-%d")

        stats_row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM attempts) AS attempts_cnt,
                (SELECT COUNT(*) FROM attempts WHERE submitted_at IS NOT NULL) AS submitted_cnt,
                (SELECT COUNT(*) FROM events) AS events_cnt
            """
        ).fetchone()
        total_attempts = int(stats_row["attempts_cnt"]) if stats_row else 0
        submitted_cnt = int(stats_row["submitted_cnt"]) if stats_row else 0
        events_cnt = int(stats_row["events_cnt"]) if stats_row else 0

        if backup_type == "solutions":
            solutions_csv_bytes = _copy_query_to_csv_bytes(
                conn,
                """
                SELECT
                    a.id AS "ID Попытки",
                    COALESCE(u.raw_key, '') AS "Код участника",
                    a.task_id AS "Задача",
                    COALESCE(a.seed::text, '') AS "Seed",
                    COALESCE(a.score::text, '') AS "Балл",
                    CASE WHEN a.submitted_at IS NOT NULL THEN 'Да' ELSE 'Нет' END AS "Сдано",
                    COALESCE(to_char(a.submitted_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'), '') AS "Дата сдачи",
                    to_char(a.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS "Дата создания",
                    COALESCE(a.answers::text, '{}') AS "Ответы (JSON)"
                FROM attempts a
                JOIN users u ON u.id = a.user_id
                WHERE a.submitted_at IS NOT NULL OR a.answers <> '{}'::jsonb
                ORDER BY a.id DESC
                """,
            )
            dump_json_bytes, saved_cnt, _ = _build_restore_dump_bytes(conn, now_utc, reason, only_meaningful=True)
            filename = f"solutions_{ts_str}.zip"
            file_path = primary_dir / filename
            with zipfile.ZipFile(file_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("solutions_with_codes.csv", solutions_csv_bytes)
                zf.writestr("full_restore_dump.json", dump_json_bytes)
            shutil.copy2(file_path, primary_dir / "latest_backup.zip")
            shutil.copy2(file_path, mirror_dir / "latest_backup.zip")

        elif backup_type == "csv_only":
            attempts_csv_bytes = _copy_query_to_csv_bytes(
                conn,
                """
                SELECT
                    a.id AS "ID Попытки",
                    COALESCE(u.raw_key, '') AS "Код участника",
                    a.task_id AS "Задача",
                    COALESCE(a.seed::text, '') AS "Seed",
                    COALESCE(a.score::text, '') AS "Балл",
                    CASE WHEN a.submitted_at IS NOT NULL THEN 'Да' ELSE 'Нет' END AS "Сдано",
                    COALESCE(to_char(a.submitted_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'), '') AS "Дата сдачи",
                    to_char(a.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS "Дата создания",
                    COALESCE(a.answers::text, '{}') AS "Ответы (JSON)"
                FROM attempts a
                JOIN users u ON u.id = a.user_id
                ORDER BY a.id DESC
                """,
            )
            filename = f"attempts_table_{ts_str}.csv"
            file_path = primary_dir / filename
            file_path.write_bytes(attempts_csv_bytes)
            (primary_dir / "attempts_latest.csv").write_bytes(attempts_csv_bytes)
            (mirror_dir / "attempts_latest.csv").write_bytes(attempts_csv_bytes)
            saved_cnt = total_attempts

        else:  # "full"
            attempts_csv_bytes = _copy_query_to_csv_bytes(
                conn,
                """
                SELECT
                    a.id AS "ID Попытки",
                    COALESCE(u.raw_key, '') AS "Код участника",
                    a.task_id AS "Задача",
                    COALESCE(a.seed::text, '') AS "Seed",
                    COALESCE(a.score::text, '') AS "Балл",
                    CASE WHEN a.submitted_at IS NOT NULL THEN 'Да' ELSE 'Нет' END AS "Сдано",
                    COALESCE(to_char(a.submitted_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'), '') AS "Дата сдачи",
                    to_char(a.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS "Дата создания",
                    COALESCE(a.answers::text, '{}') AS "Ответы (JSON)"
                FROM attempts a
                JOIN users u ON u.id = a.user_id
                ORDER BY a.id DESC
                """,
            )
            events_csv_bytes = _copy_query_to_csv_bytes(
                conn,
                """
                SELECT
                    e.id AS "ID События",
                    e.attempt_id AS "ID Попытки",
                    COALESCE(u.raw_key, '') AS "Код участника",
                    a.task_id AS "Задача",
                    to_char(e.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS "Время события",
                    e.name AS "Действие",
                    COALESCE(e.payload::text, '{}') AS "Данные (JSON)"
                FROM events e
                JOIN attempts a ON a.id = e.attempt_id
                JOIN users u ON u.id = a.user_id
                ORDER BY e.id DESC
                """,
            )
            dump_json_bytes, saved_cnt, _ = _build_restore_dump_bytes(conn, now_utc, reason, only_meaningful=False)
            filename = f"backup_{ts_str}.zip"
            file_path = primary_dir / filename
            with zipfile.ZipFile(file_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("attempts_with_codes.csv", attempts_csv_bytes)
                zf.writestr("events_log.csv", events_csv_bytes)
                zf.writestr("full_restore_dump.json", dump_json_bytes)
            shutil.copy2(file_path, primary_dir / "latest_backup.zip")
            shutil.copy2(file_path, mirror_dir / "latest_backup.zip")

        daily_path = primary_dir / f"backup_daily_{day_str}{file_path.suffix}"
        if not daily_path.exists():
            shutil.copy2(file_path, daily_path)

        _rotate_old_backups(primary_dir, cfg.get("keep_count", 10), cfg.get("keep_daily_count", 7))

        _backup_state["last_backup_at"] = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
        _backup_state["last_backup_file"] = filename
        _backup_state["last_backup_type"] = backup_type
        _backup_state["last_error"] = None
        _backup_state["total_attempts"] = total_attempts
        _backup_state["submitted_attempts"] = submitted_cnt

        gdrive_res = None
        if sync_gdrive and cfg.get("gdrive_enabled"):
            try:
                gdrive_res = upload_file_to_gdrive(file_path, cfg)
            except Exception as ge:
                logger.error("Ошибка автовыгрузки на Google Диск: %s", ge)
                _backup_state["last_gdrive_status"] = f"Ошибка: {ge}"

        return {
            "status": "ok",
            "filename": filename,
            "backup_type": backup_type,
            "created_at": _backup_state["last_backup_at"],
            "total_attempts": total_attempts,
            "saved_attempts": saved_cnt,
            "submitted_attempts": submitted_cnt,
            "events_count": events_cnt,
            "gdrive": gdrive_res,
        }
    except Exception as e:
        _backup_state["last_error"] = str(e)
        logger.error("Ошибка создания бэкапа (%s): %s", backup_type, e, exc_info=True)
        raise
    finally:
        if own_conn:
            conn.close()


def create_full_backup(conn: Optional[psycopg.Connection] = None, reason: str = "scheduled") -> Dict[str, Any]:
    cfg = load_backup_settings()
    btype = cfg.get("auto_backup_type", "solutions") if reason in ("scheduled", "periodic") else "full"
    return create_backup(conn=conn, backup_type=btype, reason=reason, sync_gdrive=(reason in ("scheduled", "periodic")))


def _rotate_old_backups(backup_dir: Path, keep_periodic: int, keep_daily: int) -> None:
    periodic = sorted(
        [
            p for p in backup_dir.iterdir()
            if p.is_file()
            and (p.name.startswith("backup_2") or p.name.startswith("solutions_2") or p.name.startswith("attempts_table_2"))
            and not p.name.startswith("backup_daily_")
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_p in periodic[max(1, keep_periodic):]:
        try:
            old_p.unlink()
        except Exception:
            pass

    daily = sorted(
        list(backup_dir.glob("backup_daily_*")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_d in daily[max(1, keep_daily):]:
        try:
            old_d.unlink()
        except Exception:
            pass


def delete_backup_files(filenames: List[str]) -> Dict[str, Any]:
    """Удаляет выбранные файлы бэкапов с диска."""
    primary_dir, mirror_dir = get_backup_dirs()
    deleted = []
    for name in filenames:
        safe_name = Path(name).name
        if not safe_name or safe_name == "backup_settings.json":
            continue
        for d in (primary_dir, mirror_dir):
            target = (d / safe_name).resolve()
            if target.is_relative_to(d.resolve()) and target.is_file():
                try:
                    target.unlink()
                    if d == primary_dir:
                        deleted.append(safe_name)
                except Exception as e:
                    logger.warning("Не удалось удалить %s: %s", target, e)
    return {"deleted": deleted, "count": len(deleted)}


# --- Выгрузка на Google Диск (с автоудалением старых копий) ---

def _get_gdrive_access_token(cfg: Dict[str, Any]) -> str:
    client_id = (cfg.get("gdrive_client_id") or "").strip()
    client_secret = (cfg.get("gdrive_client_secret") or "").strip()
    refresh_token = (cfg.get("gdrive_refresh_token") or "").strip()
    if not (client_id and client_secret and refresh_token):
        raise ValueError("Не заполнены OAuth2-поля Google Диска (Client ID, Client Secret, Refresh Token)")

    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        token = payload.get("access_token")
        if not token:
            raise ValueError(f"Google OAuth2 не вернул access_token: {payload}")
        return token


def upload_file_to_gdrive(file_path: Path, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Загружает файл бэкапа в папку Google Диска и автоматически удаляет старые бэкапы в этой папке
    сверх лимита `gdrive_keep_count`.
    """
    if cfg is None:
        cfg = load_backup_settings()
    if not file_path.is_file():
        raise FileNotFoundError(f"Файл не найден: {file_path.name}")

    access_token = _get_gdrive_access_token(cfg)
    folder_id = (cfg.get("gdrive_folder_id") or "").strip()
    keep_count = max(1, int(cfg.get("gdrive_keep_count") or 10))

    meta: Dict[str, Any] = {"name": file_path.name}
    if folder_id:
        meta["parents"] = [folder_id]

    boundary = f"===============astroprak_{uuid.uuid4().hex}=="
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(b"Content-Type: application/json; charset=UTF-8\r\n\r\n")
    body.write(json.dumps(meta).encode("utf-8"))
    body.write(f"\r\n--{boundary}\r\n".encode("utf-8"))
    body.write(b"Content-Type: application/octet-stream\r\n\r\n")
    body.write(file_path.read_bytes())
    body.write(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    up_req = urllib.request.Request(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,createdTime",
        data=body.getvalue(),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(up_req, timeout=60) as resp:
        uploaded = json.loads(resp.read().decode("utf-8"))

    # Ротация старых бэкапов в папке на Google Диске
    deleted_remote = 0
    if folder_id:
        q_str = (
            f"'{folder_id}' in parents and trashed = false and "
            "(name contains 'backup_' or name contains 'solutions_' or name contains 'attempts_table_')"
        )
        list_url = (
            "https://www.googleapis.com/drive/v3/files?"
            + urllib.parse.urlencode({
                "q": q_str,
                "orderBy": "createdTime desc",
                "pageSize": 100,
                "fields": "files(id,name,createdTime)",
            })
        )
        list_req = urllib.request.Request(
            list_url,
            headers={"Authorization": f"Bearer {access_token}"},
            method="GET",
        )
        with urllib.request.urlopen(list_req, timeout=20) as lresp:
            files_data = json.loads(lresp.read().decode("utf-8")).get("files", [])

        for old_file in files_data[keep_count:]:
            fid = old_file.get("id")
            if not fid:
                continue
            try:
                del_req = urllib.request.Request(
                    f"https://www.googleapis.com/drive/v3/files/{fid}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    method="DELETE",
                )
                with urllib.request.urlopen(del_req, timeout=15):
                    pass
                deleted_remote += 1
            except Exception as de:
                logger.warning("Не удалось удалить старый файл %s на Google Диске: %s", fid, de)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _backup_state["last_gdrive_sync_at"] = now_str
    _backup_state["last_gdrive_status"] = f"OK ({file_path.name}, удалено старых: {deleted_remote})"
    return {
        "file_id": uploaded.get("id"),
        "name": uploaded.get("name"),
        "deleted_old": deleted_remote,
        "synced_at": now_str,
    }


# --- Выгрузка в Telegram по команде ---

def send_file_to_telegram(file_path: Path, cfg: Optional[Dict[str, Any]] = None, caption: str = "") -> Dict[str, Any]:
    """Отправляет выбранный файл бэкапа документом в Telegram-чат/топик через Bot API."""
    if cfg is None:
        cfg = load_backup_settings()
    if not file_path.is_file():
        raise FileNotFoundError(f"Файл не найден: {file_path.name}")

    bot_token = (cfg.get("tg_bot_token") or "").strip()
    chat_id = (cfg.get("tg_chat_id") or "").strip()
    topic_id = (cfg.get("tg_topic_id") or "").strip()
    if not (bot_token and chat_id):
        raise ValueError("Укажите Bot Token и Chat ID в настройках Telegram")

    boundary = f"----AstroprakTgBoundary{uuid.uuid4().hex}"
    body = io.BytesIO()

    def _add_field(name: str, val: str) -> None:
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.write(f"{val}\r\n".encode("utf-8"))

    _add_field("chat_id", chat_id)
    if topic_id and topic_id.isdigit():
        _add_field("message_thread_id", topic_id)
    if caption:
        _add_field("caption", caption)

    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(
        f'Content-Disposition: form-data; name="document"; filename="{file_path.name}"\r\n'.encode("utf-8")
    )
    body.write(b"Content-Type: application/octet-stream\r\n\r\n")
    body.write(file_path.read_bytes())
    body.write(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    req = urllib.request.Request(
        url,
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as he:
        err_body = he.read().decode("utf-8", errors="ignore")
        raise ValueError(f"Ошибка Telegram API ({he.code}): {err_body}")

    if not res_data.get("ok"):
        raise ValueError(f"Ответ Telegram API: {res_data}")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _backup_state["last_tg_send_at"] = now_str
    return {"status": "ok", "sent_at": now_str, "filename": file_path.name}


def list_backups_info() -> Dict[str, Any]:
    primary_dir, _ = get_backup_dirs()
    cfg = load_backup_settings()
    files = []
    total_size_kb = 0.0
    for f in sorted(primary_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix in (".zip", ".csv", ".jsonl", ".json") and f.name != "backup_settings.json":
            st = f.stat()
            sz = round(st.st_size / 1024.0, 1)
            total_size_kb += sz
            btype = "full"
            if f.name.startswith("solutions_"):
                btype = "solutions"
            elif f.name.startswith("attempts_table_") or f.name.endswith(".csv"):
                btype = "csv_only"
            elif f.name.startswith("submitted_live_log"):
                btype = "live_log"
            files.append({
                "filename": f.name,
                "backup_type": btype,
                "size_kb": sz,
                "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            })
    return {
        "settings": cfg,
        "backup_types": list(BACKUP_TYPES_META.values()),
        "last_backup_at": _backup_state["last_backup_at"],
        "last_backup_file": _backup_state["last_backup_file"],
        "last_backup_type": _backup_state["last_backup_type"],
        "last_gdrive_sync_at": _backup_state["last_gdrive_sync_at"],
        "last_gdrive_status": _backup_state["last_gdrive_status"],
        "last_tg_send_at": _backup_state["last_tg_send_at"],
        "last_error": _backup_state["last_error"],
        "total_attempts": _backup_state["total_attempts"],
        "submitted_attempts": _backup_state["submitted_attempts"],
        "total_size_mb": round(total_size_kb / 1024.0, 2),
        "files": files,
    }


def restore_from_dump_bytes(conn: psycopg.Connection, raw_bytes: bytes, filename: str) -> Dict[str, int]:
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
                    %s, %s, %s, %s, '{}'::jsonb, %s, %s, %s, %s::timestamptz, COALESCE(%s::timestamptz, NOW())
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
    """Фоновый цикл регулярного резервного копирования с учётом динамических настроек из админки."""
    await asyncio.sleep(30)
    while True:
        try:
            cfg = load_backup_settings()
            interval_min = int(cfg.get("interval_minutes") or 0)
            if interval_min > 0:
                primary_dir, _ = get_backup_dirs()
                latest_zip = primary_dir / "latest_backup.zip"
                should_run = True
                if latest_zip.exists():
                    age_sec = time.time() - latest_zip.stat().st_mtime
                    if age_sec < (interval_min * 60 - 30):
                        should_run = False
                if should_run:
                    btype = cfg.get("auto_backup_type", "solutions")
                    await asyncio.to_thread(create_backup, None, btype, "periodic", True)
        except Exception as e:
            logger.error("Сбой в фоновом цикле бэкапа: %s", e)
        await asyncio.sleep(60)
