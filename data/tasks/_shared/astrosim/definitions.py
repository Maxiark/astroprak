"""Описания задач — JSON, независимый от seed. Здесь только чтение и подстановка строк."""
from __future__ import annotations

import json
from pathlib import Path
from string import Formatter
from typing import Any

DIRECTORY = Path(__file__).parent / "content" / "definitions"


def load_definition(task_id: str) -> dict[str, Any]:
    if not task_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in task_id):
        raise ValueError("недопустимый идентификатор задачи")
    path = DIRECTORY / f"{task_id}.json"
    if not path.is_file():
        raise ValueError(f"описание задачи не найдено: {task_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_definitions() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DIRECTORY.glob("*.json"))]


def render_text(template: str, context: dict[str, Any]) -> str:
    """Только именованные значения. Доступ к атрибутам, индексам и исполнение кода запрещены."""
    for _, name, spec, conversion in Formatter().parse(template):
        if name is not None and (not name.isidentifier() or spec or conversion):
            raise ValueError("шаблон допускает только простые именованные подстановки")
    return template.format_map(context)


def render_content(task_id: str, section: str, context: dict[str, Any]):
    definition = load_definition(task_id)
    if section == "statement":
        return {k: [render_text(s, context) for s in value] if isinstance(value, list)
                else render_text(value, context) for k, value in definition["statement_template"].items()}
    if section == "solution":
        return [render_text(step["text"], context) for step in definition["solution_template"]["steps"]]
    raise ValueError("неизвестный раздел описания задачи")
