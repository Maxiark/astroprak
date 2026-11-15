"""
Автоматически сгенерированная точка входа генератора задачи `galaxy-redshift` для платформы astroprak.
Использует единый модуль совместимости `/data/tasks/_shared/legacy_adapter.py` и пакет `astrosim`.
"""
from __future__ import annotations

import sys
from pathlib import Path

TASK_ID = 'galaxy-redshift'

_SHARED_DIR = Path(__file__).resolve().parent.parent / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from legacy_adapter import generate_legacy_task, grade_legacy_task  # noqa: E402


def generate(seed: int | None = None) -> dict:
    return generate_legacy_task(TASK_ID, seed)


def grade(seed: int, answers: dict) -> dict:
    return grade_legacy_task(TASK_ID, seed, answers)
