"""
Автоматически сгенерированная точка входа генератора задачи `2023-F-11-8`.
"""
from __future__ import annotations

import sys
from pathlib import Path

TASK_ID = '2023-F-11-8'

_SHARED_DIR = Path(__file__).resolve().parent.parent / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from legacy_adapter import generate_legacy_task, grade_legacy_task  # noqa: E402


def generate(seed: int | None = None) -> dict:
    return generate_legacy_task(TASK_ID, seed)


def grade(seed: int, answers: dict) -> dict:
    return grade_legacy_task(TASK_ID, seed, answers)
