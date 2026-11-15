"""Семейство «кривая блеска транзита → радиус планеты, орбита, равновесная температура» (curve-reading).

Прототип: 2026-F-11-7 «Планета всходит и заходит» (транзит + вторичное затмение на 8 мкм); здесь — базовая
версия: только транзит, центральное прохождение. Модель и валидация — docs/validation/transit_depth.md.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from astrosim.constants import AU, DAY, G, M_SUN, R_SUN
from astrosim.definitions import load_definition, render_content
from astrosim.tasks.base import FieldSpec, KeyEntry, TaskPackage, Verdict, allowed_sigfigs, floor_tolerance, fmt, grade_fields

FAMILY = "transit-depth"
GENERATOR_VERSION = "0.1.0"
FAMILY_LABEL = "кривая блеска транзита → радиус планеты и температура"
R_EARTH_KM = 6378.14     # экваториальный радиус Земли с листа справочных данных

FIELDS: list[FieldSpec] = [FieldSpec(**field) for field in load_definition(FAMILY)["answers"]]


def semi_major_axis_m(period_days: float, mass_star_msun: float) -> float:
    p = period_days * DAY
    return (G * mass_star_msun * M_SUN * p**2 / (4 * math.pi**2)) ** (1 / 3)


def equilibrium_temperature(t_star: float, r_star_m: float, a_m: float) -> float:
    """Баланс энергии: πR_p² · L/(4πa²) = 4πR_p² σT⁴, L = 4πR*²σT*⁴ → T_eq = T* √(R*/2a)."""
    return t_star * math.sqrt(r_star_m / (2 * a_m))


def transit_flux(t_hours: np.ndarray, t14_h: float, t23_h: float, depth: float) -> np.ndarray:
    """Трапеция: полная длительность T14, плоское дно T23; вход и выход линейные."""
    x = np.abs(t_hours)
    flat = x <= t23_h / 2
    ramp = (x > t23_h / 2) & (x < t14_h / 2)
    f = np.ones_like(t_hours)
    f[flat] = 1 - depth
    f[ramp] = 1 - depth * (t14_h / 2 - x[ramp]) / ((t14_h - t23_h) / 2)
    return f


def generate(seed: int) -> TaskPackage:
    rng = np.random.default_rng(seed)
    r_star = round(float(rng.uniform(0.5, 1.5)), 2)          # R☉
    m_star = round(float(np.clip(r_star ** 1.25 * rng.uniform(0.9, 1.1), 0.4, 1.8)), 2)   # M☉, грубо вдоль главной последовательности
    t_star = int(round(float(rng.uniform(4000, 6500)), -2))
    period = round(float(np.exp(rng.uniform(np.log(1.0), np.log(20.0)))), 3)
    k = float(rng.uniform(0.03, 0.15))                        # R_p / R*
    depth = k * k
    a_m = semi_major_axis_m(period, m_star)
    r_star_m = r_star * R_SUN
    r_p_m = k * r_star_m
    t14_h = period * 24 / math.pi * math.asin(min(1.0, (r_star_m + r_p_m) / a_m))
    t23_h = period * 24 / math.pi * math.asin(min(1.0, (r_star_m - r_p_m) / a_m))
    window = max(1.2 * t14_h, t14_h + 1.0)
    n = int(rng.integers(120, 181))
    t = np.sort(rng.uniform(-window, window, n))
    sigma_f = depth * float(rng.uniform(0.04, 0.10))
    f = transit_flux(t, t14_h, t23_h, depth) + rng.normal(0, sigma_f, n)

    tick_t = next(tk for tk in (0.25, 0.5, 1.0, 2.0) if 2 * window / tk <= 14)
    t_lim = math.ceil(window / tick_t) * tick_t
    tick_f = next(tk for tk in (0.0005, 0.001, 0.002, 0.005, 0.01, 0.02) if (depth + 8 * sigma_f) / tk <= 12)
    f_lo = math.floor((1 - depth - 4 * sigma_f) / tick_f) * tick_f
    f_hi = math.ceil((1 + 4 * sigma_f) / tick_f) * tick_f

    r_p_earth = r_p_m / (R_EARTH_KM * 1e3)
    a_au = a_m / AU
    t_eq = equilibrium_temperature(t_star, r_star_m, a_m)

    tol_depth = 2 * sigma_f + tick_f / 10
    tol_rp = r_p_earth * 0.5 * tol_depth / depth
    tol_a = 0.02 * a_au
    tol_t = t_eq * (0.01 + 0.5 * tol_a / a_au)

    designation = f"TR {1000 + seed % 9000}"
    statement = render_content(FAMILY, "statement", {
        'designation': designation,
        'fmt_r_star_2': fmt(r_star, 2),
        'fmt_m_star_2': fmt(m_star, 2),
        't_star': t_star,
        'fmt_period_3': fmt(period, 3)
    })
    public: dict[str, Any] = {
        "family_label": FAMILY_LABEL,
        "statement": statement,
        "data": {
            "series": [{"id": "F", "label": "поток", "marker": "dot", "points": [[round(float(x), 3), round(float(y), 5)] for x, y in zip(t, f)]}],
            "axes": {"x": {"label": "время от середины транзита, ч", "min": -t_lim, "max": t_lim, "tick": tick_t},
                     "y": {"label": "относительный поток", "min": f_lo, "max": f_hi, "tick": tick_f}},
        },
        "plot": {"caption": "Кривая блеска во время транзита", "x": {"key": "t", "unit": "ч", "decimals": 2}, "y": {"key": "F", "unit": "", "decimals": 4, "sign": False}},
        "fields": [f_.__dict__ for f_ in FIELDS],
        "tools": ["cursor", "loupe", "extremum", "segment"],
        "given": {"r_star_rsun": r_star, "m_star_msun": m_star, "t_star_k": t_star, "period_days": period},
    }
    key = [
        KeyEntry("depth", depth, 6, floor_tolerance(tol_depth, depth), sigfig_allowed=allowed_sigfigs(tol_depth, depth)),
        KeyEntry("radius", r_p_earth, 7, floor_tolerance(tol_rp, r_p_earth), sigfig_allowed=allowed_sigfigs(tol_rp, r_p_earth)),
        KeyEntry("a_au", a_au, 5, floor_tolerance(tol_a, a_au), sigfig_allowed=allowed_sigfigs(tol_a, a_au)),
        KeyEntry("t_eq", t_eq, 7, floor_tolerance(tol_t, t_eq), sigfig_allowed=allowed_sigfigs(tol_t, t_eq)),
    ]
    solution = render_content(FAMILY, "solution", {
        'fmt_depth': fmt(depth),
        'fmt_t14_h': fmt(t14_h),
        'fmt_t23_h': fmt(t23_h),
        'fmt_r_star_2': fmt(r_star, 2),
        'fmt_R_SUN_1000_0_3': fmt(R_SUN / 1000.0, 3),
        'fmt_math_sqrt_depth': fmt(math.sqrt(depth)),
        'fmt_r_p_m_1000_0_3': fmt(r_p_m / 1000.0, 3),
        'fmt_r_p_earth': fmt(r_p_earth),
        'fmt_a_m_1000_0_3': fmt(a_m / 1000.0, 3),
        'fmt_a_au': fmt(a_au),
        't_star': t_star,
        'fmt_r_star_m_1000_0_3': fmt(r_star_m / 1000.0, 3),
        'fmt_t_eq': fmt(t_eq)
    })
    private = {
        "truth": {"r_star": r_star, "m_star": m_star, "t_star": t_star, "period": period, "k": k, "depth": depth, "sigma_f": sigma_f,
                  "t14_h": t14_h, "t23_h": t23_h, "radius": r_p_earth, "a_au": a_au, "t_eq": t_eq},
        "key": [k_.__dict__ for k_ in key],
        "solution": solution,
    }
    return TaskPackage(FAMILY, GENERATOR_VERSION, seed, public, private)


def grade(package: TaskPackage, answers: dict[str, str]) -> Verdict:
    key = [KeyEntry(**k_) for k_ in package.private["key"]]
    return grade_fields(FIELDS, key, answers)
