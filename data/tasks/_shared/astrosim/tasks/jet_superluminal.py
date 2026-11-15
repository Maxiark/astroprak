"""Семейство «узлы джета по эпохам → сверхсветовое движение → скорость джета» (image-series-motion, радио).

Прототип: 2026-F-11-9 «Гонки за светом» (М. В. Костина, П. А. Тараканов): одиннадцать РСДБ-карт на 22 ГГц
за 2001 год, угол между джетом и лучом зрения 15°, z = 0,033; требуется 1 − v/c. Официальное решение советует
нанести положения узла по эпохам и взять наклон прямой — здесь такая диаграмма «расстояние от ядра — эпоха»
и есть данные задания. Критерий оттуда же: измерение по двум и более узлам — полный балл, по одному — минус 2
(docs/research/format.md §3). Модель и валидация — docs/validation/jet_superluminal.md.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from astrosim.constants import AU, C, PC, YEAR_TROPICAL
from astrosim.definitions import load_definition, render_content
from astrosim.tasks.base import FieldSpec, KeyEntry, TaskPackage, Verdict, allowed_sigfigs, floor_tolerance, fmt, grade_fields

FAMILY = "jet-superluminal"
GENERATOR_VERSION = "0.1.0"
FAMILY_LABEL = "узлы джета по эпохам → сверхсветовое движение → скорость джета"
H0_KM_S_MPC = 70.0                                   # постоянная Хаббла с листа справочных данных
C_KM_S = C / 1e3
KM_S_PER_ARCSEC_YR_PC = AU / YEAR_TROPICAL / 1e3     # 1″/год на 1 пк = 1 а. е./год ≈ 4,74 км/с

FIELDS: list[FieldSpec] = [FieldSpec(**field) for field in load_definition(FAMILY)["answers"]]


def hubble_distance_mpc(z: float) -> float:
    """r = cz/H при z ≪ 1."""
    return C_KM_S * z / H0_KM_S_MPC


def apparent_speed_c(beta: float, theta_deg: float) -> float:
    """Видимая скорость в картинной плоскости: u/c = β sin θ / (1 − β cos θ)."""
    th = math.radians(theta_deg)
    return beta * math.sin(th) / (1 - beta * math.cos(th))


def beta_from_apparent(u_c: float, theta_deg: float) -> float:
    """Обратно: β = u / (sin θ + u cos θ), u в долях c."""
    th = math.radians(theta_deg)
    return u_c / (math.sin(th) + u_c * math.cos(th))


def proper_motion_mas_per_yr(u_c: float, r_mpc: float) -> float:
    """μ = u / r: скорость в км/с, расстояние в пк → ″/год через 4,74 км/с; наружу — мсд/год."""
    return u_c * C_KM_S / (KM_S_PER_ARCSEC_YR_PC * r_mpc * 1e6) * 1e3


def generate(seed: int) -> TaskPackage:
    rng = np.random.default_rng(seed)
    for _ in range(500):
        z = round(float(rng.uniform(0.008, 0.035)), 3)
        theta = int(rng.integers(8, 31))
        beta = float(rng.uniform(0.95, 0.995))
        u = apparent_speed_c(beta, theta)
        # относительная ошибка u переносится на 1 − β с множителем A = β(1 − β cos θ)/(1 − β); при β → 1 он
        # неограничен, поэтому берём только системы, где ответ ещё осмыслен при ошибке u в несколько процентов
        amplification = beta * (1 - beta * math.cos(math.radians(theta))) / (1 - beta)
        if 3.0 <= u <= 10.0 and amplification <= 4.0:
            break
    else:                                            # практически недостижимо
        raise RuntimeError("не удалось подобрать джет")
    r_mpc = hubble_distance_mpc(z)
    mu = proper_motion_mas_per_yr(u, r_mpc)
    one_minus_beta = 1 - beta

    n = int(rng.integers(9, 13))
    span = round(float(rng.uniform(0.8, 1.5)), 2)
    t = np.round(np.linspace(0.0, span, n), 2)
    s_a = round(float(rng.uniform(2.0, 5.0)), 1)
    s_b = round(s_a + float(rng.uniform(3.0, 6.0)), 1)
    sigma = round(0.02 * mu * span + 0.03, 3)          # мсд: доля пройденного пути плюс предел точности карты
    y_a = s_a + mu * t + rng.normal(0, sigma, n)
    y_b = s_b + mu * t + rng.normal(0, sigma, n)

    tick_t = next(tk for tk in (0.1, 0.2, 0.25, 0.5) if span / tk <= 14)
    t_hi = math.ceil(span / tick_t) * tick_t
    y_max = s_b + mu * span + 3 * sigma
    tick_y = next(tk for tk in (0.5, 1.0, 2.0, 5.0, 10.0, 20.0) if y_max / tk <= 14)
    y_hi = math.ceil(y_max / tick_y) * tick_y

    # допуски: наклон по хорде «первая — последняя точка» одного узла имеет σ = √2 σ/span; среднее по двум узлам — σ/span.
    # Сеточного члена нет: курсор прилипает к точкам. r: z дан с тремя цифрами (≈1,5 %) плюс округление c.
    tol_mu = 2 * sigma / span
    tol_r = 0.02 * r_mpc
    rel_u = math.hypot(tol_mu / mu, 0.02)
    tol_u = u * rel_u
    th = math.radians(theta)
    tol_omb = math.sin(th) / (math.sin(th) + u * math.cos(th)) ** 2 * tol_u    # dβ/du · tol_u

    designation = f"J{seed % 24:02d}{seed * 7 % 60:02d}+{seed * 13 % 90:02d}{seed * 3 % 60:02d}"
    statement = render_content(FAMILY, "statement", {
        'designation': designation,
        'fmt_span_2': fmt(span, 2),
        'fmt_z_3': fmt(z, 3),
        'theta': theta
    })
    public: dict[str, Any] = {
        "family_label": FAMILY_LABEL,
        "statement": statement,
        "data": {
            "series": [
                {"id": "A", "label": "узел A", "marker": "dot", "points": [[float(x), round(float(y), 3)] for x, y in zip(t, y_a)]},
                {"id": "B", "label": "узел B", "marker": "ring", "points": [[float(x), round(float(y), 3)] for x, y in zip(t, y_b)]},
            ],
            "axes": {"x": {"label": "эпоха, годы от первой карты", "min": 0.0, "max": t_hi, "tick": tick_t},
                     "y": {"label": "расстояние от ядра, мсд", "min": 0.0, "max": y_hi, "tick": tick_y}},
        },
        "plot": {"caption": "Узлы джета: расстояние от ядра по эпохам", "x": {"key": "t", "unit": "год", "decimals": 2},
                 "y": {"key": "s", "unit": "мсд", "decimals": 2, "sign": False}},
        "fields": [f.__dict__ for f in FIELDS],
        "tools": ["cursor", "loupe", "segment"],
        "given": {"z": z, "theta_deg": theta, "span_yr": span, "hubble": H0_KM_S_MPC},
    }
    key = [
        KeyEntry("mu", mu, 7, floor_tolerance(tol_mu, mu), sigfig_allowed=allowed_sigfigs(tol_mu, mu)),
        KeyEntry("distance", r_mpc, 4, floor_tolerance(tol_r, r_mpc), sigfig_allowed=allowed_sigfigs(tol_r, r_mpc)),
        KeyEntry("apparent", u, 6, floor_tolerance(tol_u, u), sigfig_allowed=allowed_sigfigs(tol_u, u)),
        KeyEntry("one_minus_beta", one_minus_beta, 8, floor_tolerance(tol_omb, one_minus_beta),
                 sigfig_allowed=allowed_sigfigs(tol_omb, one_minus_beta)),
    ]
    slope_a = (y_a[-1] - y_a[0]) / span
    slope_b = (y_b[-1] - y_b[0]) / span
    u_kms = u * C_KM_S
    solution = render_content(FAMILY, "solution", {
        'fmt_slope_a_3': fmt(slope_a, 3),
        'fmt_slope_b_3': fmt(slope_b, 3),
        'fmt_mu': fmt(mu),
        'fmt_sigma_2': fmt(sigma, 2),
        'fmt_z_3': fmt(z, 3),
        'fmt_r_mpc': fmt(r_mpc),
        'fmt_KM_S_PER_ARCSEC_YR_PC_3': fmt(KM_S_PER_ARCSEC_YR_PC, 3),
        'fmt_mu_0_001_3': fmt(mu * 0.001, 3),
        'fmt_r_mpc_1000000_0_3': fmt(r_mpc * 1000000.0, 3),
        'fmt_u_kms_3': fmt(u_kms, 3),
        'fmt_u': fmt(u),
        'fmt_math_sin_th_3': fmt(math.sin(th), 3),
        'fmt_math_cos_th_3': fmt(math.cos(th), 3),
        'fmt_beta_4': fmt(beta, 4),
        'fmt_one_minus_beta': fmt(one_minus_beta)
    })
    private = {
        "truth": {"z": z, "theta_deg": theta, "beta": beta, "one_minus_beta": one_minus_beta, "apparent": u, "distance_mpc": r_mpc,
                  "mu": mu, "sigma": sigma, "span": span, "n": n, "s_a": s_a, "s_b": s_b},
        "key": [k.__dict__ for k in key],
        "solution": solution,
    }
    return TaskPackage(FAMILY, GENERATOR_VERSION, seed, public, private)


def grade(package: TaskPackage, answers: dict[str, str]) -> Verdict:
    key = [KeyEntry(**k) for k in package.private["key"]]
    return grade_fields(FIELDS, key, answers)
