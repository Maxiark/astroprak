"""
Семейство PowerVertical: подбор параметров экспоненциального диска Галактики.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from astrosim.definitions import load_definition, render_content
from astrosim.tasks.base import FieldSpec, KeyEntry, TaskPackage, Verdict, allowed_sigfigs, floor_tolerance, fmt, grade_fields

FAMILY = "power-vertical"
GENERATOR_VERSION = "0.1.0"
FAMILY_LABEL = "вертикальный диск → статистика → шкала высот h"

FIELDS: list[FieldSpec] = [
    FieldSpec(**{k: v for k, v in field.items() if k != "options"})
    for field in load_definition(FAMILY)["answers"]
]


def generate(seed: int) -> TaskPackage:
    rng = np.random.default_rng(seed)
    
    N_count = 100
    h_true = round(float(rng.uniform(0.15, 0.25)), 3)
    f_disk = 0.85
    N_disk = int(N_count * f_disk)
    N_bg = N_count - N_disk

    u = rng.uniform(0, 1, size=N_disk)
    sign = rng.choice([-1.0, 1.0], size=N_disk)
    z_disk = sign * (-h_true * np.log(1.0 - u * (1.0 - np.exp(-1.0 / h_true))))
    z_bg = rng.uniform(-1.0, 1.0, size=N_bg)

    z_points = np.concatenate([z_disk, z_bg])
    rng.shuffle(z_points)
    z_points = [round(float(z), 3) for z in z_points]

    n0_true = round(float(N_disk / (2.0 * h_true * (1.0 - np.exp(-1.0 / h_true)))), 1)

    tol_h = h_true * 0.15
    tol_n0 = n0_true * 0.20

    statement = render_content(FAMILY, "statement", {
        "N_count": N_count
    })

    public: dict[str, Any] = {
        "family_label": FAMILY_LABEL,
        "statement": statement,
        "data": {
            "z_points": z_points,
            "z_min": -1.0,
            "z_max": 1.0
        },
        "fields": [f.__dict__ for f in FIELDS],
        "tools": ["cursor", "loupe"],
        "given": {"N_count": N_count}
    }

    key = [
        KeyEntry("model_type", "Профиль D (Заострённый пик и спадающие крылья)", 1, 0.0),
        KeyEntry("h_val", h_true, 3, floor_tolerance(tol_h, h_true), sigfig_allowed=allowed_sigfigs(tol_h, h_true)),
        KeyEntry("n0_val", n0_true, 3, floor_tolerance(tol_n0, n0_true), sigfig_allowed=allowed_sigfigs(tol_n0, n0_true))
    ]

    solution = render_content(FAMILY, "solution", {
        "fmt_h_true": fmt(h_true, 3),
        "fmt_n0_true": fmt(n0_true, 1)
    })

    private = {
        "truth": {"model_type": "exponential", "h_true": h_true, "n0_true": n0_true},
        "key": [k.__dict__ for k in key],
        "solution": solution,
    }

    return TaskPackage(FAMILY, GENERATOR_VERSION, seed, public, private)


def grade(package: TaskPackage, answers: dict[str, str]) -> Verdict:
    key = [KeyEntry(**k) for k in package.private["key"]]
    return grade_fields(FIELDS, key, answers)
