"""Семейство «высота аппарата от времени при спуске на парашюте → скорость от высоты → температура атмосферы»
(curve-reading, Солнечная система).

Прототип: 2023-F-11-8 «Перед посадкой»: радиолокатор пишет высоту, сопротивление ∝ ρv², концентрация
больцмановская, атмосфера из N₂; требуется температура (в оригинале 150 К с точностью 10 К). Критерий оттуда же:
скорости нужно снять «хотя бы на трёх — четырёх высотах», по двум — минус 2 балла; без двойки в показателе
экспоненты температура завышается вдвое. Модель и валидация — docs/validation/descent_profile.md.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from astrosim.definitions import load_definition, render_content
from astrosim.tasks.base import FieldSpec, KeyEntry, TaskPackage, Verdict, allowed_sigfigs, floor_tolerance, fmt, grade_fields

FAMILY = "descent-profile"
GENERATOR_VERSION = "0.1.0"
FAMILY_LABEL = "спуск на парашюте → скорость от высоты → температура атмосферы"
R_GAS = 8.31                                  # Дж/(моль·К), с листа справочных данных
GASES = [("азота N₂", 0.028), ("углекислого газа CO₂", 0.044)]

FIELDS: list[FieldSpec] = [FieldSpec(**field) for field in load_definition(FAMILY)["answers"]]


def scale_height_m(temperature_k: float, molar_mass: float, g: float) -> float:
    """H = ℛT/(μg)."""
    return R_GAS * temperature_k / (molar_mass * g)


def speed_at(h_m: float | np.ndarray, v0: float, scale_m: float) -> float | np.ndarray:
    """Равновесный спуск: K n v² = g при n ∝ exp(−h/H) даёт v = v₀ exp(h/2H)."""
    return v0 * np.exp(np.asarray(h_m, dtype=float) / (2 * scale_m))


def time_to_reach(h_m: float, h0_m: float, v0: float, scale_m: float) -> float:
    """Время спуска с h₀ до h: t = (2H/v₀)(e^{−h/2H} − e^{−h₀/2H}) — интеграл dh/v."""
    return 2 * scale_m / v0 * (math.exp(-h_m / (2 * scale_m)) - math.exp(-h0_m / (2 * scale_m)))


def height_at(t_s: np.ndarray, h0_m: float, v0: float, scale_m: float) -> np.ndarray:
    """Обращение time_to_reach: h(t) = −2H ln(e^{−h₀/2H} + v₀t/2H)."""
    return -2 * scale_m * np.log(math.exp(-h0_m / (2 * scale_m)) + v0 * np.asarray(t_s, dtype=float) / (2 * scale_m))


def generate(seed: int) -> TaskPackage:
    rng = np.random.default_rng(seed)
    gas_name, molar = GASES[int(rng.integers(0, len(GASES)))]
    g = round(float(rng.uniform(7.5, 12.0)), 1)
    temperature = float(rng.integers(120, 321))
    scale = scale_height_m(temperature, molar, g)
    v0 = round(float(rng.uniform(3.0, 8.0)), 1)
    # начальная высота ≈ 6 шкал высот (в разумных пределах): тогда скорость между h₁ и h₂ меняется в 3–8 раз,
    # и плечо для ln v достаточно длинное
    h0 = float(np.clip(round(6 * scale / 1e3), 15, 60)) * 1e3
    h1 = round(0.2 * h0 / 1e3) * 1e3
    h2 = round(0.75 * h0 / 1e3) * 1e3
    t_end = time_to_reach(500.0, h0, v0, scale)          # до посадки не дошли: последняя точка на 0,5 км
    n = int(rng.integers(110, 161))
    t = np.sort(np.round(rng.uniform(0, t_end, n), 1))
    sigma_h = round(float(rng.uniform(0.03, 0.08)), 3)    # км, шум радиолокатора
    h_km = height_at(t, h0, v0, scale) / 1e3 + rng.normal(0, sigma_h, n)

    tick_t = next(tk for tk in (100.0, 200.0, 250.0, 500.0, 1000.0) if t_end / tk <= 14)
    t_hi = math.ceil(t_end / tick_t) * tick_t
    tick_h = 5.0 if h0 <= 50e3 else 10.0
    h_hi = math.ceil((h0 / 1e3 + 3 * sigma_h) / tick_h) * tick_h

    v1 = float(speed_at(h1, v0, scale))
    v2 = float(speed_at(h2, v0, scale))
    scale_km = scale / 1e3

    # допуски: скорость — наклон хорды между точками по обе стороны от h (±2 км): σ_v = √2 σ_h v / (2·2 км); плюс 2 % на округление
    rel_v = 2 * math.sqrt(2) * sigma_h / 4.0 + 0.02
    tol_v1, tol_v2 = v1 * rel_v, v2 * rel_v
    ratio = v2 / v1
    rel_h = math.sqrt(2) * rel_v / math.log(ratio)
    tol_h = scale_km * rel_h
    tol_t = temperature * (rel_h + 0.01)

    designation = f"КА-{100 + seed % 900}"
    statement = render_content(FAMILY, "statement", {
        'designation': designation,
        'fmt_g_2': fmt(g, 2),
        'gas_name': gas_name,
        'fmt_molar_3': fmt(molar, 3),
        'int_h1_1000_0': int(h1 / 1000.0),
        'int_h2_1000_0': int(h2 / 1000.0)
    })
    public: dict[str, Any] = {
        "family_label": FAMILY_LABEL,
        "statement": statement,
        "data": {
            "series": [{"id": "h", "label": "высота", "marker": "dot", "points": [[float(x), round(float(y), 3)] for x, y in zip(t, h_km)]}],
            "axes": {"x": {"label": "время, с", "min": 0.0, "max": t_hi, "tick": tick_t},
                     "y": {"label": "высота, км", "min": 0.0, "max": h_hi, "tick": tick_h}},
        },
        "plot": {"caption": "Высота аппарата по данным радиолокатора", "x": {"key": "t", "unit": "с", "decimals": 0},
                 "y": {"key": "h", "unit": "км", "decimals": 2, "sign": False}},
        "fields": [f.__dict__ for f in FIELDS],
        "tools": ["cursor", "loupe", "segment"],
        "given": {"g": g, "molar_mass": molar, "h1_km": h1 / 1e3, "h2_km": h2 / 1e3},
    }
    key = [
        KeyEntry("v_1", v1, 6, floor_tolerance(tol_v1, v1), sigfig_allowed=allowed_sigfigs(tol_v1, v1)),
        KeyEntry("v_2", v2, 6, floor_tolerance(tol_v2, v2), sigfig_allowed=allowed_sigfigs(tol_v2, v2)),
        KeyEntry("scale_height", scale_km, 6, floor_tolerance(tol_h, scale_km), sigfig_allowed=allowed_sigfigs(tol_h, scale_km)),
        KeyEntry("temperature", temperature, 7, floor_tolerance(tol_t, temperature), sigfig_allowed=allowed_sigfigs(tol_t, temperature)),
    ]
    solution = render_content(FAMILY, "solution", {
        'int_h1_1000_0': int(h1 / 1000.0),
        'fmt_v1': fmt(v1),
        'int_h2_1000_0': int(h2 / 1000.0),
        'fmt_v2': fmt(v2),
        'fmt_ratio_3': fmt(ratio, 3),
        'fmt_scale_km': fmt(scale_km),
        'fmt_molar_3': fmt(molar, 3),
        'fmt_g_2': fmt(g, 2),
        'fmt_scale_3': fmt(scale, 3),
        'fmt_temperature': fmt(temperature)
    })
    private = {
        "truth": {"temperature": temperature, "scale_height_km": scale_km, "g": g, "molar_mass": molar, "gas": gas_name,
                  "v0": v0, "h0_km": h0 / 1e3, "h1_km": h1 / 1e3, "h2_km": h2 / 1e3, "v_1": v1, "v_2": v2,
                  "sigma_h_km": sigma_h, "t_end_s": t_end},
        "key": [k.__dict__ for k in key],
        "solution": solution,
    }
    return TaskPackage(FAMILY, GENERATOR_VERSION, seed, public, private)


def grade(package: TaskPackage, answers: dict[str, str]) -> Verdict:
    key = [KeyEntry(**k) for k in package.private["key"]]
    return grade_fields(FIELDS, key, answers)
