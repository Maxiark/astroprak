import asyncio
import csv
import io
import json
import logging
import os
import random
import re
import secrets
import shutil
import time
import zipfile
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response as RawResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.backup import (
    PRIMARY_BACKUP_DIR,
    append_live_submission_backup,
    create_backup,
    delete_backup_files,
    list_backups_info,
    periodic_backup_loop,
    restore_from_dump_bytes,
    save_backup_settings,
    send_file_to_telegram,
    upload_file_to_gdrive,
)
from core.db import (
    DATABASE_URL,
    compact_database,
    finalize_attempt,
    get_db,
    get_db_size_info,
    get_or_create_user,
    hash_key,
    init_db,
)
from core.task_loader import TASKS_DIR, registry

logger = logging.getLogger(__name__)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or "dev-admin"
DOCS_DIR = Path("/app/docs")
CATEGORIES_FILE = TASKS_DIR.parent / "categories.json"
COOKIE_MAX_AGE = 31536000  # 1 год (п. 2.2 ТЗ)

FAILED_ATTEMPTS = defaultdict(list)
BLOCK_DURATION = 900
MAX_FAILURES = 5

HEX_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}$")

SECRET_DATA_KEYS = {
    "h_model",
    "n0_model",
    "rc_model",
    "true_counts",
    "true_densities",
    "alpha_core",
    "delta_core",
    "truth",
    "key",
    "solution",
    "answer_checks",
    "private",
}


def normalize_key(key: Optional[str]) -> Optional[str]:
    if not key or not isinstance(key, str):
        return None
    cleaned = key.strip().lower()
    return cleaned if HEX_KEY_PATTERN.match(cleaned) else None


def strip_secret_task_data(task_obj: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(task_obj, dict):
        return task_obj
    cleaned = dict(task_obj)
    if isinstance(cleaned.get("data"), dict):
        cleaned["data"] = {
            k: v for k, v in cleaned["data"].items() if k not in SECRET_DATA_KEYS
        }
    cleaned.pop("private", None)
    return cleaned


def _generate_clean_task_payload(task_id: str, task_seed: int) -> dict[str, Any]:
    """Генерирует публичные данные задачи на лету по (task_id, seed) без хранения мегабайт в БД."""
    generator = registry.get_generator(task_id)
    manifest = registry.get_manifest(task_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if generator and hasattr(generator, "generate"):
        raw_task_data = generator.generate(task_seed)
    else:
        raw_task_data = {
            "id": task_id,
            "title": manifest.get("title", task_id),
            "max_score": manifest.get("max_score", 0.0),
            "entry_point": manifest.get("entry_point", "widget.html"),
            "data": {},
            "schema": {"fields": []},
        }
    return strip_secret_task_data(raw_task_data)


# --- Инициализация приложения FastAPI ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Запуск ядра Astrosite...")
    init_db()
    registry.scan()
    backup_task = asyncio.create_task(periodic_backup_loop())
    try:
        yield
    finally:
        backup_task.cancel()


app = FastAPI(title="Astrosite V2 Core API", lifespan=lifespan)

raw_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if raw_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=raw_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )


@app.middleware("http")
async def security_and_static_guard(request: Request, call_next):
    path_lower = request.url.path.lower()

    if path_lower.startswith("/static/tasks"):
        parts = [p for p in path_lower.split("/") if p]
        filename = parts[-1] if parts else ""
        forbidden_ext = (".py", ".pyc", ".pyo", ".pyd", ".env", ".sql", ".sh", ".jsonl", ".zip")
        forbidden_files = {"manifest.json", "task.json", "solution.json", "import.json"}
        if (
            filename.endswith(forbidden_ext)
            or filename in forbidden_files
            or "__pycache__" in parts
            or "_backups" in parts
            or "astrosim" in parts
            or "solution" in parts
        ):
            return RawResponse(status_code=404, content="Not Found")

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


app.mount("/static/tasks", StaticFiles(directory=TASKS_DIR), name="tasks_static")


# --- Модели Pydantic ---

class EventsBatch(BaseModel):
    events: List[Dict[str, Any]]


class SubmitPayload(BaseModel):
    answers: Dict[str, Any]


class RestoreKeyPayload(BaseModel):
    key: str


class AnswersDraftPayload(BaseModel):
    answers: dict[str, Any]


class CategoriesOrderPayload(BaseModel):
    categories: list[str]


class TaskCategoryPayload(BaseModel):
    category: str
    category_order: int = 100


class BackupCreatePayload(BaseModel):
    backup_type: str = "solutions"
    sync_gdrive: bool = False


class BackupDeletePayload(BaseModel):
    filenames: List[str]


class BackupSendTelegramPayload(BaseModel):
    filename: Optional[str] = None
    backup_type: str = "solutions"


class BackupSyncGdrivePayload(BaseModel):
    filename: Optional[str] = None


class DbCompactPayload(BaseModel):
    delete_short_attempts: bool = False


# --- Вспомогательные функции авторизации и сессий ---
def _is_secure_request(request: Request) -> bool:
    if os.getenv("COOKIE_SECURE", "0") == "1":
        return True
    proto = request.headers.get("x-forwarded-proto", "").lower()
    if "https" in proto:
        return True
    return request.url.scheme == "https"


def _set_session_cookie(request: Request, response: Response, raw_key: str) -> None:
    response.set_cookie(
        key="astrosite_key",
        value=raw_key,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_is_secure_request(request),
        path="/",
    )


def get_current_user_or_create(
    request: Request,
    response: Response,
    astrosite_key: Optional[str] = Cookie(default=None),
    conn: psycopg.Connection = Depends(get_db),
) -> Tuple[int, str]:
    user_id, raw_key = get_or_create_user(conn, astrosite_key)
    if astrosite_key != raw_key:
        _set_session_cookie(request, response, raw_key)
    return user_id, raw_key


def require_current_user(
    request: Request,
    astrosite_key: Optional[str] = Cookie(default=None),
    conn: psycopg.Connection = Depends(get_db),
) -> Tuple[int, str]:
    clean_key = normalize_key(astrosite_key)
    if not clean_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SESSION_REQUIRED", "message": "Действительная сессия не найдена"},
        )
    h = hash_key(clean_key)
    row = conn.execute("SELECT id, raw_key FROM users WHERE key_hash = %s", (h,)).fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SESSION_REQUIRED", "message": "Пользователь с данной cookie не найден"},
        )
    return row["id"], row["raw_key"]


def verify_admin(request: Request, authorization: Optional[str] = Header(default=None)):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    FAILED_ATTEMPTS[client_ip] = [t for t in FAILED_ATTEMPTS[client_ip] if now - t < BLOCK_DURATION]
    if len(FAILED_ATTEMPTS[client_ip]) >= MAX_FAILURES:
        retry_after = int(BLOCK_DURATION - (now - FAILED_ATTEMPTS[client_ip][0]))
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много неудачных попыток входа. Доступ заблокирован на {retry_after} сек.",
        )

    if not authorization or not authorization.startswith("Bearer "):
        FAILED_ATTEMPTS[client_ip].append(now)
        raise HTTPException(status_code=401, detail="Требуется заголовок авторизации")

    token = authorization.split(" ", 1)[1].strip()
    if token != ADMIN_TOKEN:
        FAILED_ATTEMPTS[client_ip].append(now)
        remaining = MAX_FAILURES - len(FAILED_ATTEMPTS[client_ip])
        raise HTTPException(
            status_code=403,
            detail=f"Неверный токен администратора. Осталось попыток: {max(0, remaining)}",
        )

    FAILED_ATTEMPTS.pop(client_ip, None)
    return True


# --- Публичные эндпоинты ---

@app.get("/api/me")
def get_me(
    request: Request,
    response: Response,
    conn: psycopg.Connection = Depends(get_db),
    astrosite_key: Optional[str] = Cookie(default=None),
):
    user_id, raw_key = get_current_user_or_create(request, response, astrosite_key, conn)
    response.headers["Cache-Control"] = "no-store"
    return {"user_id": user_id, "recovery_code": raw_key}


@app.post("/api/restore")
def restore_session(
    request: Request,
    payload: RestoreKeyPayload,
    response: Response,
    conn: psycopg.Connection = Depends(get_db),
):
    clean_key = normalize_key(payload.key)
    if not clean_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_RECOVERY_CODE",
                "message": "Ключ должен состоять ровно из 32 шестнадцатеричных символов (0-9, a-f).",
            },
        )

    h = hash_key(clean_key)
    row = conn.execute("SELECT id, raw_key FROM users WHERE key_hash = %s", (h,)).fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "INVALID_RECOVERY_CODE", "message": "Сессия с таким ключом не найдена."},
        )

    _set_session_cookie(request, response, clean_key)
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok", "recovery_code": clean_key, "message": "Сессия восстановлена"}


@app.get("/api/tasks")
def get_catalogue():
    return {"tasks": registry.get_all_manifests(include_hidden=False)}


@app.post("/api/attempts")
def create_attempt(
    task_id: str,
    seed: Optional[int] = None,
    new: bool = Query(False),
    user_info: Tuple[int, str] = Depends(get_current_user_or_create),
    conn: psycopg.Connection = Depends(get_db),
):
    user_id, recovery_code = user_info

    if not new and seed is None:
        existing = conn.execute(
            """
            SELECT id, seed, answers, submitted_at, score, grading, created_at
            FROM attempts 
            WHERE user_id = %s AND task_id = %s
            ORDER BY (submitted_at IS NULL) DESC, created_at DESC 
            LIMIT 1
            """,
            (user_id, task_id),
        ).fetchone()

        if existing:
            is_sub = existing["submitted_at"] is not None
            ex_seed = existing["seed"] if existing["seed"] is not None else 42
            try:
                task_payload = _generate_clean_task_payload(task_id, ex_seed)
            except Exception:
                task_payload = {"id": task_id, "data": {}, "schema": {"fields": []}}

            grading_payload = existing.get("grading") if is_sub else None
            # Если попытка сдана, но из БД были очищены тяжелые картинки разбора, достраиваем их на лету
            if is_sub and isinstance(grading_payload, dict) and "solution_steps" not in grading_payload:
                gen_mod = registry.get_generator(task_id)
                if gen_mod and hasattr(gen_mod, "grade"):
                    try:
                        full_gr = gen_mod.grade(ex_seed, existing["answers"] or {})
                        if isinstance(full_gr, dict):
                            grading_payload = full_gr
                    except Exception:
                        pass

            return {
                "status": "ok",
                "attempt_id": str(existing["id"]),
                "recovery_code": recovery_code,
                "task": task_payload,
                "answers": existing["answers"] or {},
                "submitted": is_sub,
                "score": existing.get("score"),
                "grading": grading_payload,
                "created_at": existing["created_at"].isoformat() if existing.get("created_at") else None,
            }

    task_seed = seed if seed is not None else random.randint(1000, 999999)
    try:
        task_data = _generate_clean_task_payload(task_id, task_seed)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Сбой генератора {task_id}: {e}")
        raise HTTPException(status_code=422, detail=f"Ошибка генератора задачи {task_id}")

    # В БД сохраняем только пустой объект task_data='{}', чтобы не раздувать диск гигабайтами base64-картинок!
    row = conn.execute(
        """
        INSERT INTO attempts (user_id, task_id, seed, task_data)
        VALUES (%s, %s, %s, '{}'::jsonb)
        RETURNING id, created_at
        """,
        (user_id, task_id, task_seed),
    ).fetchone()
    conn.commit()

    return {
        "status": "ok",
        "attempt_id": str(row["id"]),
        "recovery_code": recovery_code,
        "task": task_data,
        "answers": {},
        "submitted": False,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


@app.patch("/api/attempts/{attempt_id}/answers")
def save_attempt_draft(
    attempt_id: int,
    payload: AnswersDraftPayload,
    user_info: Tuple[int, str] = Depends(require_current_user),
    conn: psycopg.Connection = Depends(get_db),
):
    user_id, _ = user_info
    attempt = conn.execute(
        "SELECT id, user_id, answers, submitted_at FROM attempts WHERE id = %s",
        (attempt_id,),
    ).fetchone()
    if not attempt:
        raise HTTPException(status_code=404, detail={"code": "ATTEMPT_NOT_FOUND", "message": "Попытка не найдена"})

    if attempt["user_id"] != user_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "SESSION_MISMATCH", "message": "Попытка не принадлежит текущей сессии"},
        )

    prev_answers = attempt.get("answers") or {}
    saved = conn.execute(
        "UPDATE attempts SET answers = %s, updated_at = NOW() "
        "WHERE id = %s AND user_id = %s AND submitted_at IS NULL RETURNING id",
        (psycopg.types.json.Jsonb(payload.answers), attempt_id, user_id),
    ).fetchone()
    if saved is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "ATTEMPT_ALREADY_SUBMITTED", "message": "Работа уже сдана"},
        )
    if payload.answers != prev_answers:
        conn.execute(
            "INSERT INTO events (attempt_id, name, payload) VALUES (%s, %s, %s)",
            (attempt_id, "answer.save", psycopg.types.json.Jsonb(payload.answers)),
        )
    conn.commit()
    return {"status": "ok"}


@app.post("/api/attempts/{attempt_id}/events")
def save_events(
    attempt_id: int,
    batch: EventsBatch,
    user_info: Tuple[int, str] = Depends(require_current_user),
    conn: psycopg.Connection = Depends(get_db),
):
    user_id, _ = user_info
    own = conn.execute("SELECT id FROM attempts WHERE id = %s AND user_id = %s", (attempt_id, user_id)).fetchone()
    if not own:
        raise HTTPException(status_code=404, detail={"code": "ATTEMPT_NOT_FOUND", "message": "Попытка не найдена"})

    events_to_save = (batch.events or [])[:100]
    for item in events_to_save:
        conn.execute(
            "INSERT INTO events (attempt_id, name, payload) VALUES (%s, %s, %s)",
            (attempt_id, str(item.get("name", "unknown"))[:64], psycopg.types.json.Jsonb(item.get("payload", {}))),
        )
    conn.execute("UPDATE attempts SET updated_at = NOW() WHERE id = %s", (attempt_id,))
    conn.commit()
    return {"status": "ok", "saved": len(events_to_save)}


@app.post("/api/attempts/{attempt_id}/submit")
def submit_attempt(
    attempt_id: int,
    payload: SubmitPayload,
    user_info: Tuple[int, str] = Depends(require_current_user),
    conn: psycopg.Connection = Depends(get_db),
):
    user_id, recovery_code = user_info
    attempt = conn.execute(
        "SELECT id, user_id, task_id, seed, answers, score, grading, submitted_at FROM attempts WHERE id = %s",
        (attempt_id,),
    ).fetchone()
    if not attempt:
        raise HTTPException(status_code=404, detail={"code": "ATTEMPT_NOT_FOUND", "message": "Попытка не найдена"})

    if attempt["user_id"] != user_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "SESSION_MISMATCH", "message": "Попытка не принадлежит текущей сессии"},
        )

    task_id = attempt["task_id"]
    att_seed = attempt.get("seed", 42)

    def accepted_response(row):
        grading = row.get("grading")
        return {
            "status": "ok",
            "attempt_id": str(attempt_id),
            "recovery_code": recovery_code,
            "submitted_at": row["submitted_at"].isoformat(),
            "answers": row["answers"],
            "score": row.get("score"),
            "max_score": grading.get("max_score", 10.0) if isinstance(grading, dict) else 10.0,
            "grading": grading,
        }

    if attempt["submitted_at"] is not None:
        return accepted_response(attempt)

    score = None
    grading_details = None

    try:
        mod = registry.get_generator(task_id)
        if mod and hasattr(mod, "grade"):
            res = mod.grade(att_seed, payload.answers or {})
            if isinstance(res, dict):
                score = res.get("score")
                grading_details = res
    except Exception as e:
        logger.error(f"Ошибка проверки решения {task_id}: {e}")

    accepted = finalize_attempt(
        conn=conn,
        attempt_id=attempt_id,
        user_id=user_id,
        answers=payload.answers or {},
        score=score,
        grading=grading_details,
    )
    if accepted is None:
        accepted = conn.execute(
            "SELECT answers, score, grading, submitted_at FROM attempts WHERE id = %s AND user_id = %s",
            (attempt_id, user_id),
        ).fetchone()
        return accepted_response(accepted)

    response = accepted_response(accepted)
    conn.execute(
        "INSERT INTO events (attempt_id, name, payload) VALUES (%s, %s, %s)",
        (
            attempt_id,
            "attempt.submit",
            psycopg.types.json.Jsonb({
                "score": response["score"], "max_score": response["max_score"],
                "answers": accepted["answers"],
            }),
        ),
    )
    conn.commit()

    append_live_submission_backup(
        attempt_id=attempt_id,
        user_id=user_id,
        student_key=recovery_code,
        task_id=task_id,
        seed=att_seed,
        score=accepted["score"],
        max_score=response["max_score"],
        answers=accepted["answers"],
        grading=accepted["grading"],
        submitted_at=response["submitted_at"],
    )
    return response


# --- Междоменный перенос сессий ---

@app.get("/api/auth/prepare-transfer")
def prepare_session_transfer(
    path: str = Query("/"),
    user_info: Tuple[int, str] = Depends(require_current_user),
    conn: psycopg.Connection = Depends(get_db),
):
    user_id, _ = user_info
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    conn.execute(
        "INSERT INTO session_transfers (token, user_id, target_path, expires_at) VALUES (%s, %s, %s, %s)",
        (token, user_id, path, expires),
    )
    conn.commit()
    return {"transfer_token": token}


@app.get("/api/auth/complete-transfer")
def complete_session_transfer(
    token: str = Query(...),
    request: Request = None,
    response: Response = None,
    conn: psycopg.Connection = Depends(get_db),
):
    row = conn.execute(
        """
        DELETE FROM session_transfers 
        WHERE token = %s AND expires_at > NOW() 
        RETURNING user_id, target_path
        """,
        (token,),
    ).fetchone()

    if not row:
        return RedirectResponse(url="/?transfer_error=expired", status_code=302)

    user = conn.execute("SELECT raw_key FROM users WHERE id = %s", (row["user_id"],)).fetchone()
    if not user:
        return RedirectResponse(url="/?transfer_error=user_not_found", status_code=302)

    redirect_resp = RedirectResponse(url=row["target_path"] or "/", status_code=302)
    _set_session_cookie(request, redirect_resp, user["raw_key"])
    return redirect_resp


# --- Категории задач ---

def get_persisted_categories() -> list[str]:
    default_order = [
        "Интерактивные практикумы и тренажёры",
        "Архив ВсОШ / 9 класс",
        "Архив ВсОШ / 10 класс",
        "Архив ВсОШ / 11 класс",
        "Архив ВсОШ (Практический тур)",
        "Звёздная астрономия",
        "Общие задачи",
    ]
    if not CATEGORIES_FILE.exists():
        return default_order
    try:
        with open(CATEGORIES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else default_order
    except Exception:
        return default_order


@app.get("/api/categories")
def get_categories():
    return {"categories": get_persisted_categories()}


@app.post("/api/admin/categories/order")
def admin_set_categories_order(
    payload: CategoriesOrderPayload,
    admin: bool = Depends(verify_admin),
):
    try:
        clean_cats = [c.strip() for c in payload.categories if c and c.strip()]
        with open(CATEGORIES_FILE, "w", encoding="utf-8") as f:
            json.dump(clean_cats, f, ensure_ascii=False, indent=2)
        return {"status": "success", "categories": clean_cats}
    except Exception as e:
        logger.error(f"Не удалось сохранить категории: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/tasks/{task_id}/category")
def admin_set_task_category(
    task_id: str,
    payload: TaskCategoryPayload,
    admin: bool = Depends(verify_admin),
):
    task_dir = TASKS_DIR / task_id
    manifest_path = task_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Манифест не найден")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    manifest.setdefault("tags", {})
    manifest["tags"]["category"] = payload.category.strip()
    manifest["tags"]["category_order"] = int(payload.category_order)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    registry.scan()
    return {"status": "success", "category": payload.category, "category_order": payload.category_order}


# --- Админ-панель: Задачи ---

@app.get("/api/admin/tasks")
def admin_list_tasks(admin: bool = Depends(verify_admin)):
    result = []
    if TASKS_DIR.exists():
        for task_dir in sorted(TASKS_DIR.iterdir()):
            if not task_dir.is_dir() or task_dir.name.startswith(("_", ".")):
                continue
            t_id = task_dir.name
            manifest_file = task_dir / "manifest.json"
            error_desc = None
            if not manifest_file.exists():
                error_desc = "Отсутствует manifest.json"
            manifest = registry.get_manifest(t_id)
            if manifest_file.exists() and not manifest:
                error_desc = "Ошибка структуры JSON или синтаксиса в generator.py"

            result.append({
                "id": t_id,
                "valid": manifest is not None,
                "hidden": manifest.get("hidden", False) if manifest else False,
                "title": manifest.get("title") if manifest else None,
                "category_order": (manifest.get("tags", {}) or {}).get("category_order", 100) if manifest else 100,
                "category": (manifest.get("tags", {}) or {}).get("category", "") if manifest else "",
                "has_generator": (task_dir / "generator.py").exists(),
                "has_widget": (task_dir / "widget.html").exists(),
                "error": error_desc,
            })
    return {"tasks": result}


@app.post("/api/admin/tasks/{task_id}/toggle-visibility")
def admin_toggle_task_visibility(task_id: str, admin: bool = Depends(verify_admin)):
    task_dir = TASKS_DIR / task_id
    manifest_path = task_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Манифест задачи не найден")

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        new_hidden = not manifest_data.get("hidden", False)
        manifest_data["hidden"] = new_hidden

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, ensure_ascii=False, indent=2)

        registry.scan()
        return {
            "status": "success",
            "task_id": task_id,
            "hidden": new_hidden,
            "message": f"Задача '{task_id}' {'скрыта' if new_hidden else 'доступна'}",
        }
    except Exception as e:
        logger.error(f"Не удалось обновить видимость задачи: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/tasks/{task_id}")
def admin_delete_task(task_id: str, admin: bool = Depends(verify_admin)):
    task_dir = TASKS_DIR / task_id
    if not task_dir.exists() or not task_dir.is_dir():
        raise HTTPException(status_code=404, detail="Директория задачи не найдена")

    try:
        shutil.rmtree(task_dir)
        registry.scan()
        return {"status": "success", "message": f"Задача '{task_id}' удалена"}
    except Exception as e:
        logger.error(f"Не удалось удалить задачу: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Админ-панель: Пагинация сессий, сквозной поиск и фильтр «Скрыть все < 5 с» ---

def _build_attempts_where(
    q: Optional[str] = None,
    task_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    exclude_short: bool = False,
) -> tuple[str, list[Any]]:
    """
    Формирует быстрые условия фильтрации по таблице attempts + users.
    При exclude_short=True скрывает ВСЕ попытки длительностью < 5 секунд независимо от их статуса (сдано или в процессе).
    """
    clauses: list[str] = []
    params: list[Any] = []

    if q and q.strip():
        clean_q = q.strip()
        id_cand = clean_q.lstrip("#")
        like_pat = f"%{clean_q}%"
        if id_cand.isdigit():
            clauses.append("(a.id = %s OR u.raw_key ILIKE %s OR a.task_id ILIKE %s)")
            params.extend([int(id_cand), like_pat, like_pat])
        else:
            clauses.append("(u.raw_key ILIKE %s OR a.task_id ILIKE %s OR CAST(a.id AS TEXT) ILIKE %s)")
            params.extend([like_pat, like_pat, like_pat])

    if task_id and task_id.strip():
        clauses.append("a.task_id = %s")
        params.append(task_id.strip())

    if status_filter == "submitted":
        clauses.append("a.submitted_at IS NOT NULL")
    elif status_filter == "in_progress":
        clauses.append("a.submitted_at IS NULL")

    if exclude_short:
        clauses.append(
            """
            GREATEST(
                0,
                EXTRACT(
                    EPOCH FROM (
                        GREATEST(
                            a.created_at,
                            COALESCE(a.submitted_at, a.created_at),
                            COALESCE(a.updated_at, a.created_at),
                            COALESCE((SELECT MAX(e.created_at) FROM events e WHERE e.attempt_id = a.id), a.created_at)
                        ) - LEAST(
                            a.created_at,
                            COALESCE((SELECT MIN(e.created_at) FROM events e WHERE e.attempt_id = a.id), a.created_at)
                        )
                    )
                )::int
            ) >= 5
            """
        )

    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where_sql, params


@app.get("/api/admin/sessions")
def admin_list_sessions(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    exclude_short: bool = Query(False),
    admin: bool = Depends(verify_admin),
    conn: psycopg.Connection = Depends(get_db),
):
    where_sql, params = _build_attempts_where(q, task_id, status_filter, exclude_short)

    if not where_sql:
        total_row = conn.execute("SELECT COUNT(*) AS total FROM attempts").fetchone()
    else:
        total_row = conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM attempts a
            JOIN users u ON u.id = a.user_id
            {where_sql}
            """,
            tuple(params),
        ).fetchone()
    total_count = int(total_row["total"]) if total_row else 0

    rows = conn.execute(
        f"""
        WITH page_attempts AS (
            SELECT
                a.id AS attempt_id,
                a.user_id,
                u.raw_key AS user_key,
                a.task_id,
                a.seed,
                a.answers,
                a.score,
                a.grading,
                a.submitted_at,
                a.updated_at,
                a.created_at
            FROM attempts a
            JOIN users u ON u.id = a.user_id
            {where_sql}
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT %s OFFSET %s
        )
        SELECT
            p.*,
            COALESCE(ev.events_count, 0) AS events_count,
            GREATEST(
                0,
                EXTRACT(
                    EPOCH FROM (
                        GREATEST(
                            p.created_at,
                            COALESCE(p.submitted_at, p.created_at),
                            COALESCE(p.updated_at, p.created_at),
                            COALESCE(ev.last_event, p.created_at)
                        ) - LEAST(
                            p.created_at,
                            COALESCE(ev.first_event, p.created_at)
                        )
                    )
                )::int
            ) AS duration_sec
        FROM page_attempts p
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) AS events_count,
                MIN(e.created_at) AS first_event,
                MAX(e.created_at) AS last_event
            FROM events e
            WHERE e.attempt_id = p.attempt_id
        ) ev ON TRUE
        ORDER BY p.created_at DESC, p.attempt_id DESC
        """,
        tuple(params + [limit, offset]),
    ).fetchall()

    result = []
    for r in rows:
        result.append({
            "attempt_id": r["attempt_id"],
            "user_id": r["user_id"],
            "user_key": r["user_key"] or f"user_{r['user_id']}",
            "task_id": r["task_id"],
            "seed": r["seed"],
            "answers": r["answers"],
            "score": r["score"],
            "grading": r["grading"],
            "submitted": r["submitted_at"] is not None,
            "submitted_at": r["submitted_at"].strftime("%Y-%m-%d %H:%M") if r["submitted_at"] else None,
            "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M"),
            "events_count": int(r["events_count"] or 0),
            "duration_sec": int(r["duration_sec"] or 0),
        })
    return {
        "sessions": result,
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(result)) < total_count,
    }


@app.get("/api/admin/sessions/{attempt_id}/events")
def admin_get_attempt_events(
    attempt_id: int,
    admin: bool = Depends(verify_admin),
    conn: psycopg.Connection = Depends(get_db),
):
    rows = conn.execute(
        "SELECT name, payload, created_at FROM events WHERE attempt_id = %s ORDER BY created_at ASC, id ASC",
        (attempt_id,),
    ).fetchall()
    return {
        "events": [
            {
                "name": r["name"],
                "payload": r["payload"],
                "time": r["created_at"].strftime("%H:%M:%S"),
            }
            for r in rows
        ]
    }


@app.get("/api/admin/sessions/{attempt_id}/export/json")
def admin_export_attempt_json(
    attempt_id: int,
    admin: bool = Depends(verify_admin),
    conn: psycopg.Connection = Depends(get_db),
):
    attempt = conn.execute(
        """
        SELECT a.id, a.user_id, u.raw_key, a.task_id, a.seed, a.score, a.grading, a.answers, a.submitted_at, a.created_at
        FROM attempts a
        JOIN users u ON u.id = a.user_id
        WHERE a.id = %s
        """,
        (attempt_id,),
    ).fetchone()

    if not attempt:
        raise HTTPException(status_code=404, detail="Попытка не найдена")

    events = conn.execute(
        "SELECT name, payload, created_at FROM events WHERE attempt_id = %s ORDER BY created_at ASC, id ASC",
        (attempt_id,),
    ).fetchall()

    data = {
        "attempt_id": attempt["id"],
        "user_id": attempt["user_id"],
        "student_key": attempt["raw_key"],
        "task_id": attempt["task_id"],
        "seed": attempt["seed"],
        "score": attempt.get("score"),
        "grading": attempt.get("grading"),
        "answers": attempt["answers"],
        "submitted": attempt["submitted_at"] is not None,
        "submitted_at": str(attempt["submitted_at"]) if attempt["submitted_at"] else None,
        "created_at": str(attempt["created_at"]),
        "events": [
            {"name": e["name"], "payload": e["payload"], "time": str(e["created_at"])}
            for e in events
        ],
    }

    content = json.dumps(data, ensure_ascii=False, indent=2)
    return RawResponse(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=attempt_{attempt_id}.json"},
    )


def _stream_postgres_copy_csv(select_query: str, params: tuple[Any, ...]) -> Any:
    yield b"\xef\xbb\xbf"
    with psycopg.connect(DATABASE_URL) as stream_conn:
        if not params:
            copy_stmt = f"COPY ({select_query}) TO STDOUT WITH (FORMAT CSV, HEADER, DELIMITER ';')"
            with stream_conn.cursor() as cur:
                with cur.copy(copy_stmt) as copy:
                    for chunk in copy:
                        yield bytes(chunk)
        else:
            with stream_conn.cursor() as cur:
                cur.execute(select_query, params)
                buf = io.StringIO()
                writer = csv.writer(buf, delimiter=";")
                if cur.description:
                    writer.writerow([col.name for col in cur.description])
                    yield buf.getvalue().encode("utf-8")
                    buf.seek(0)
                    buf.truncate(0)
                while True:
                    rows = cur.fetchmany(1000)
                    if not rows:
                        break
                    writer.writerows(rows)
                    yield buf.getvalue().encode("utf-8")
                    buf.seek(0)
                    buf.truncate(0)


@app.get("/api/admin/sessions/export/csv")
def admin_export_all_csv(
    q: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    exclude_short: bool = Query(False),
    admin: bool = Depends(verify_admin),
):
    where_sql, params = _build_attempts_where(q, task_id, status_filter, exclude_short)

    select_query = f"""
        SELECT 
            a.id AS "ID Попытки",
            COALESCE(u.raw_key, '') AS "Код ученика",
            a.task_id AS "Задача",
            COALESCE(a.seed::text, '') AS "Seed",
            COALESCE(a.score::text, '') AS "Балл",
            CASE WHEN a.submitted_at IS NOT NULL THEN 'Да' ELSE 'Нет' END AS "Сдано",
            COALESCE(to_char(a.submitted_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI'), '') AS "Дата сдачи",
            to_char(a.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI') AS "Дата создания",
            COALESCE(a.answers::text, '{{}}') AS "Ответы (JSON)"
        FROM attempts a
        JOIN users u ON u.id = a.user_id
        {where_sql}
        ORDER BY a.created_at DESC, a.id DESC
    """

    return StreamingResponse(
        _stream_postgres_copy_csv(select_query, tuple(params)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=astrosite_sessions.csv"},
    )


@app.get("/api/admin/sessions/export/events-csv")
def admin_export_all_events_csv(
    q: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    exclude_short: bool = Query(False),
    admin: bool = Depends(verify_admin),
):
    where_sql, params = _build_attempts_where(q, task_id, status_filter, exclude_short)

    select_query = f"""
        SELECT
            e.id AS "ID События",
            a.id AS "ID Попытки",
            COALESCE(u.raw_key, '') AS "Код ученика",
            a.task_id AS "Задача",
            COALESCE(a.seed::text, '') AS "Seed",
            COALESCE(a.score::text, '') AS "Балл",
            CASE WHEN a.submitted_at IS NOT NULL THEN 'Да' ELSE 'Нет' END AS "Сдано",
            to_char(e.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS "Время действия",
            e.name AS "Тип действия",
            COALESCE(e.payload::text, '{{}}') AS "Данные действия (JSON)"
        FROM events e
        JOIN attempts a ON a.id = e.attempt_id
        JOIN users u ON u.id = a.user_id
        {where_sql}
        ORDER BY a.id DESC, e.created_at ASC, e.id ASC
    """

    return StreamingResponse(
        _stream_postgres_copy_csv(select_query, tuple(params)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=astrosite_all_events_log.csv"},
    )


@app.get("/api/admin/sessions/export/full-json")
def admin_export_all_sessions_json(
    q: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    exclude_short: bool = Query(True),
    admin: bool = Depends(verify_admin),
    conn: psycopg.Connection = Depends(get_db),
):
    where_sql, params = _build_attempts_where(q, task_id, status_filter, exclude_short)

    rows = conn.execute(
        f"""
        SELECT 
            a.id AS attempt_id,
            a.user_id,
            u.raw_key AS student_key,
            a.task_id,
            a.seed,
            a.score,
            a.grading,
            a.answers,
            a.submitted_at,
            a.created_at
        FROM attempts a
        JOIN users u ON u.id = a.user_id
        {where_sql}
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT 5000
        """,
        tuple(params),
    ).fetchall()

    attempt_ids = [r["attempt_id"] for r in rows]
    events_by_attempt: Dict[int, list[dict[str, Any]]] = {}
    if attempt_ids:
        ev_rows = conn.execute(
            """
            SELECT attempt_id, name, payload, created_at
            FROM events
            WHERE attempt_id = ANY(%s)
            ORDER BY created_at ASC, id ASC
            """,
            (attempt_ids,),
        ).fetchall()
        for ev in ev_rows:
            events_by_attempt.setdefault(ev["attempt_id"], []).append({
                "name": ev["name"],
                "payload": ev["payload"],
                "time": ev["created_at"].isoformat() if ev["created_at"] else None,
            })

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total_sessions": len(rows),
        "sessions": [
            {
                "attempt_id": r["attempt_id"],
                "user_id": r["user_id"],
                "student_key": r["student_key"],
                "task_id": r["task_id"],
                "seed": r["seed"],
                "score": r["score"],
                "grading": r["grading"],
                "answers": r["answers"],
                "submitted": r["submitted_at"] is not None,
                "submitted_at": r["submitted_at"].isoformat() if r["submitted_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "events": events_by_attempt.get(r["attempt_id"], []),
            }
            for r in rows
        ],
    }

    content = json.dumps(payload, ensure_ascii=False, indent=2)
    return RawResponse(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=astrosite_all_sessions_with_logs.json"},
    )


# --- Админ-панель: Управление бэкапами, Google Диском, Telegram и сжатием БД ---

@app.get("/api/admin/backups")
def admin_get_backups(
    admin: bool = Depends(verify_admin),
    conn: psycopg.Connection = Depends(get_db),
):
    info = list_backups_info()
    info["db_size"] = get_db_size_info(conn)
    return info


@app.post("/api/admin/backups/settings")
def admin_update_backup_settings(
    payload: Dict[str, Any],
    admin: bool = Depends(verify_admin),
):
    updated = save_backup_settings(payload)
    return {
        "status": "success",
        "message": "Настройки резервного копирования сохранены!",
        "settings": updated,
        "state": list_backups_info(),
    }


@app.post("/api/admin/backups/create")
def admin_trigger_backup(
    payload: Optional[BackupCreatePayload] = None,
    backup_type: str = Query("solutions"),
    admin: bool = Depends(verify_admin),
    conn: psycopg.Connection = Depends(get_db),
):
    btype = payload.backup_type if payload and payload.backup_type else backup_type
    sync_gd = payload.sync_gdrive if payload else False
    info = create_backup(conn=conn, backup_type=btype, reason="manual_admin", sync_gdrive=sync_gd)
    return {
        "status": "success",
        "message": f"Резервная копия «{info['filename']}» создана (записей: {info['saved_attempts']})",
        "backup": info,
        "state": list_backups_info(),
    }


@app.post("/api/admin/backups/delete")
def admin_delete_backups(
    payload: BackupDeletePayload,
    admin: bool = Depends(verify_admin),
):
    res = delete_backup_files(payload.filenames or [])
    return {
        "status": "success",
        "message": f"Удалено файлов резервных копий: {res['count']}",
        "deleted": res["deleted"],
        "state": list_backups_info(),
    }


@app.post("/api/admin/backups/send-telegram")
def admin_send_backup_telegram(
    payload: BackupSendTelegramPayload,
    admin: bool = Depends(verify_admin),
    conn: psycopg.Connection = Depends(get_db),
):
    try:
        if payload.filename:
            safe_name = Path(payload.filename).name
            target = (PRIMARY_BACKUP_DIR / safe_name).resolve()
            if not target.is_relative_to(PRIMARY_BACKUP_DIR.resolve()) or not target.is_file():
                raise HTTPException(status_code=404, detail="Файл бэкапа не найден")
            caption = f"📦 Бэкап Astrosite: {safe_name}"
        else:
            binfo = create_backup(conn=conn, backup_type=payload.backup_type or "solutions", reason="telegram_manual")
            target = PRIMARY_BACKUP_DIR / binfo["filename"]
            caption = (
                f"📦 Бэкап Astrosite ({binfo['backup_type']})\n"
                f"Файл: {binfo['filename']}\n"
                f"Всего попыток: {binfo['total_attempts']} (сдано: {binfo['submitted_attempts']})"
            )

        tg_res = send_file_to_telegram(target, caption=caption)
        return {
            "status": "success",
            "message": f"Файл «{target.name}» успешно отправлен в Telegram!",
            "telegram": tg_res,
            "state": list_backups_info(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/backups/sync-gdrive")
def admin_sync_backup_gdrive(
    payload: BackupSyncGdrivePayload,
    admin: bool = Depends(verify_admin),
    conn: psycopg.Connection = Depends(get_db),
):
    try:
        if payload.filename:
            safe_name = Path(payload.filename).name
            target = (PRIMARY_BACKUP_DIR / safe_name).resolve()
            if not target.is_relative_to(PRIMARY_BACKUP_DIR.resolve()) or not target.is_file():
                raise HTTPException(status_code=404, detail="Файл бэкапа не найден")
        else:
            binfo = create_backup(conn=conn, backup_type="solutions", reason="gdrive_manual")
            target = PRIMARY_BACKUP_DIR / binfo["filename"]

        gd_res = upload_file_to_gdrive(target)
        return {
            "status": "success",
            "message": (
                f"Файл «{target.name}» загружен на Google Диск! "
                f"Удалено старых копий сверх лимита: {gd_res['deleted_old']}."
            ),
            "gdrive": gd_res,
            "state": list_backups_info(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/db/compact")
def admin_compact_database(
    payload: DbCompactPayload,
    admin: bool = Depends(verify_admin),
):
    try:
        res = compact_database(delete_short_attempts=payload.delete_short_attempts)
        return {
            "status": "success",
            "message": (
                f"База данных сжата: было {res['before_mb']} МБ → стало {res['after_mb']} МБ "
                f"(освобождено {res['freed_mb']} МБ, очищено кэшей задач: {res['cleaned_bloat_rows']}, "
                f"удалено коротких попыток <5с: {res['deleted_short_rows']})."
            ),
            "result": res,
        }
    except Exception as e:
        logger.error("Ошибка сжатия БД: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка сжатия БД: {e}")


@app.get("/api/admin/backups/download/{filename}")
def admin_download_backup(
    filename: str,
    admin: bool = Depends(verify_admin),
):
    safe_name = Path(filename).name
    target = (PRIMARY_BACKUP_DIR / safe_name).resolve()
    if not target.is_relative_to(PRIMARY_BACKUP_DIR.resolve()) or not target.is_file():
        raise HTTPException(status_code=404, detail="Файл резервной копии не найден")
    return FileResponse(
        path=target,
        filename=safe_name,
        media_type="application/octet-stream",
    )


@app.post("/api/admin/backups/restore")
def admin_restore_backup(
    file: UploadFile = File(...),
    admin: bool = Depends(verify_admin),
    conn: psycopg.Connection = Depends(get_db),
):
    try:
        raw_bytes = file.file.read()
        stats = restore_from_dump_bytes(conn, raw_bytes, file.filename or "dump.json")
        return {
            "status": "success",
            "message": (
                f"База успешно восстановлена из {file.filename}: "
                f"пользователей — {stats['restored_users']}, "
                f"попыток — {stats['restored_attempts']}, "
                f"действий — {stats['restored_events']}."
            ),
            "stats": stats,
        }
    except Exception as e:
        logger.error("Ошибка восстановления из бэкапа: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=f"Не удалось восстановить бэкап: {e}")


# --- Документация и загрузка задач ---

@app.get("/api/admin/docs/export/zip")
def admin_export_docs_zip(admin: bool = Depends(verify_admin)):
    if not DOCS_DIR.exists() or not DOCS_DIR.is_dir():
        raise HTTPException(status_code=404, detail="Директория docs не найдена на сервере")

    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(DOCS_DIR):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(DOCS_DIR)
                zf.write(full_path, arcname=str(rel_path))

    mem_zip.seek(0)
    return StreamingResponse(
        mem_zip,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=astrosite_docs_and_template.zip"},
    )


@app.post("/api/admin/tasks/rescan")
def admin_rescan(admin: bool = Depends(verify_admin)):
    registry.scan()
    return {"status": "success", "loaded": len(registry.manifests)}


@app.post("/api/admin/tasks/upload")
def admin_upload_zip(
    file: UploadFile = File(...),
    overwrite: bool = Query(False),
    admin: bool = Depends(verify_admin),
):
    if not file.filename.endswith(".zip"):
        return JSONResponse(status_code=400, content={"detail": "Разрешены только архивы .zip"})

    try:
        archive = zipfile.ZipFile(file.file)
        names = archive.namelist()

        manifest_name = next((n for n in names if Path(n).name == "manifest.json"), None)
        html_name = next((n for n in names if Path(n).name.endswith(".html")), None)

        if not manifest_name and not html_name:
            return JSONResponse(
                status_code=422,
                content={"detail": "В архиве должен быть хотя бы manifest.json или .html файл"},
            )

        if manifest_name:
            prefix = manifest_name.rsplit("manifest.json", 1)[0]
            manifest_data = json.loads(archive.read(manifest_name).decode("utf-8"))
            task_id = manifest_data.get("id")
        else:
            raw_id = Path(file.filename).stem.lower().replace(" ", "-")
            task_id = "".join(c for c in raw_id if c.isalnum() or c in ("-", "_"))
            prefix = html_name.rsplit(Path(html_name).name, 1)[0]
            manifest_data = {
                "schema_version": "2.0",
                "id": task_id,
                "title": Path(file.filename).stem,
                "kind": "theory",
                "version": "1.0.0",
                "hidden": False,
                "tags": {
                    "category": "Справочные материалы",
                    "topic": "теория",
                },
                "max_score": 0.0,
                "entry_point": Path(html_name).name,
            }

        target_dir = (TASKS_DIR / task_id).resolve()
        if target_dir.exists() and not overwrite:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "conflict",
                    "task_id": task_id,
                    "title": manifest_data.get("title", task_id),
                    "message": f"Задача с ID '{task_id}' уже существует. Заменить её?",
                },
            )

        if target_dir.exists() and overwrite:
            shutil.rmtree(target_dir)

        target_dir.mkdir(parents=True, exist_ok=True)

        for member in names:
            if member.startswith(prefix) and not member.endswith("/"):
                rel_path = member[len(prefix):]
                dest_file = (target_dir / rel_path).resolve()
                if not dest_file.is_relative_to(target_dir):
                    continue
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(dest_file, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        if not manifest_name:
            with open(target_dir / "manifest.json", "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, ensure_ascii=False, indent=2)

        registry.scan()
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "task_id": task_id,
                "message": f"Материал '{task_id}' успешно опубликован в каталог!",
            },
        )

    except Exception as e:
        logger.error(f"Ошибка загрузки архива: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка на стороне сервера: {str(e)}"},
        )
