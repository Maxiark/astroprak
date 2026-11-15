"""Семейство «кривая блеска цефеиды → период → расстояние» (curve-reading).

Прототип по духу: 2024-F-10-7 «Главная из цефеид» (кривые блеска δ Cep); здесь — классическая задача на
зависимость период–светимость и модуль расстояния. Форма кривой блеска синтетическая (быстрый подъём,
медленный спад), физическое содержание — в соотношении период–светимость и модуле расстояния;
см. docs/validation/cepheid_pl.md.

Соотношение период–светимость даётся в условии: M_V = −4,05 − 2,43 (lg P − 1)
(Benedict et al. 2007, AJ 133, 1810, DOI 10.1086/511980, таблица 12, вариант с поправкой Лутца–Келкера).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from astrosim.definitions import load_definition, render_content
from astrosim.tasks.base import FieldSpec, KeyEntry, TaskPackage, Verdict, allowed_sigfigs, floor_tolerance, fmt, grade_fields

FAMILY = "cepheid-pl"
GENERATOR_VERSION = "0.1.0"
FAMILY_LABEL = "кривая блеска цефеиды → период → расстояние"
PL_ZERO, PL_SLOPE = -4.05, -2.43     # M_V = PL_ZERO + PL_SLOPE (lg P − 1)

FIELDS: list[FieldSpec] = [FieldSpec(**field) for field in load_definition(FAMILY)["answers"]]


def brightness(phase: np.ndarray) -> np.ndarray:
    """Форма кривой: подъём за 0,25 периода, спад за 0,75; +1 в максимуме блеска (φ = 0,25), −1 в минимуме (φ = 0)."""
    phi = np.mod(phase, 1.0)
    warped = np.where(phi < 0.25, phi / 0.25 * 0.5, 0.5 + (phi - 0.25) / 0.75 * 0.5)
    return -np.cos(2 * np.pi * warped)


def abs_mag(period_days: float) -> float:
    return PL_ZERO + PL_SLOPE * (math.log10(period_days) - 1)


def distance_pc(m: float, M: float) -> float:
    return 10 ** ((m - M + 5) / 5)


def generate(seed: int) -> TaskPackage:
    rng = np.random.default_rng(seed)
    period = round(float(np.exp(rng.uniform(np.log(2.0), np.log(40.0)))), 3)
    mean_mag = round(float(rng.uniform(8.0, 14.0)), 2)
    amp = round(float(rng.uniform(0.4, 1.2)), 2)
    sigma_m = round(float(rng.uniform(0.02, 0.05)), 3)
    cycles = float(rng.uniform(3.5, 5.5))
    n = int(rng.integers(70, 101))
    t0 = float(rng.uniform(0, period))      # фаза начала наблюдений случайна
    t = np.sort(rng.uniform(0, cycles * period, n))
    m = mean_mag - amp / 2 * brightness((t + t0) / period) + rng.normal(0, sigma_m, n)

    span = cycles * period
    tick_t = next(tk for tk in (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0) if span / tk <= 14)
    t_hi = math.ceil(span / tick_t) * tick_t
    tick_m = 0.1 if amp <= 0.7 else 0.2
    m_lo = math.floor((mean_mag - amp / 2 - 3 * sigma_m) / tick_m) * tick_m
    m_hi = math.ceil((mean_mag + amp / 2 + 3 * sigma_m) / tick_m) * tick_m

    M = abs_mag(period)
    d = distance_pc(mean_mag, M)

    tol_p = max(0.02 * period, tick_t / 5)
    tol_m = 2 * sigma_m + tick_m / 10
    tol_a = 2 * tol_m
    tol_M = abs(PL_SLOPE) * tol_p / (period * math.log(10))
    tol_d = d * 0.2 * math.log(10) * math.hypot(tol_m, tol_M)

    designation = f"CV {1000 + seed % 9000}"
    statement = render_content(FAMILY, "statement", {
        'designation': designation
    })
    public: dict[str, Any] = {
        "family_label": FAMILY_LABEL,
        "statement": statement,
        "data": {
            "series": [{"id": "V", "label": "полоса V", "marker": "dot", "points": [[round(float(x), 3), round(float(y), 3)] for x, y in zip(t, m)]}],
            "axes": {"x": {"label": "время, сут", "min": 0.0, "max": t_hi, "tick": tick_t},
                     "y": {"label": "m_V", "min": m_lo, "max": m_hi, "tick": tick_m, "inverted": True}},
        },
        "plot": {"caption": "Кривая блеска в полосе V", "x": {"key": "t", "unit": "сут", "decimals": 2}, "y": {"key": "m", "unit": "ᵐ", "decimals": 2, "sign": False}},
        "fields": [f.__dict__ for f in FIELDS],
        "tools": ["cursor", "loupe", "extremum", "segment"],
        "given": {"pl_zero": PL_ZERO, "pl_slope": PL_SLOPE},
    }
    key = [
        KeyEntry("period", period, 6, floor_tolerance(tol_p, period), sigfig_allowed=allowed_sigfigs(tol_p, period)),
        KeyEntry("mean_mag", mean_mag, 3, floor_tolerance(tol_m, mean_mag), sigfig_allowed=allowed_sigfigs(tol_m, mean_mag)),
        KeyEntry("amplitude", amp, 3, floor_tolerance(tol_a, amp), sigfig_allowed=allowed_sigfigs(tol_a, amp)),
        KeyEntry("abs_mag", M, 5, floor_tolerance(tol_M, M), sigfig_allowed=allowed_sigfigs(tol_M, M)),
        KeyEntry("distance", d, 8, floor_tolerance(tol_d, d), sigfig_allowed=allowed_sigfigs(tol_d, d)),
    ]
    solution = render_content(FAMILY, "solution", {
        'int_cycles': int(cycles),
        'int_cycles_1': int(cycles) + 1,
        'fmt_period_3': fmt(period, 3),
        'fmt_mean_mag_amp_2_3': fmt(mean_mag - amp / 2, 3),
        'fmt_mean_mag_amp_2_34': fmt(mean_mag + amp / 2, 3),
        'fmt_mean_mag_3': fmt(mean_mag, 3),
        'fmt_amp': fmt(amp),
        'fmt_math_log10_period_1': fmt(math.log10(period) - 1),
        'fmt_M_3': fmt(M, 3),
        'fmt_M_39': fmt(-M, 3),
        'fmt_math_log10_d_3': fmt(math.log10(d), 3),
        'fmt_d': fmt(d)
    })
    private = {
        "truth": {"period": period, "mean_mag": mean_mag, "amplitude": amp, "sigma_m": sigma_m, "abs_mag": M, "distance": d, "cycles": cycles},
        "key": [k.__dict__ for k in key],
        "solution": solution,
    }
    return TaskPackage(FAMILY, GENERATOR_VERSION, seed, public, private)


def grade(package: TaskPackage, answers: dict[str, str]) -> Verdict:
    key = [KeyEntry(**k) for k in package.private["key"]]
    return grade_fields(FIELDS, key, answers)
