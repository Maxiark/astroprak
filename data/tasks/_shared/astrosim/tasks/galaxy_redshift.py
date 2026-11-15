"""Семейство «спектр галактики → наблюдаемые длины волн линий → красное смещение → расстояние» (curve-reading, спектры).

Прототипы: 2024-R-11-6 «Спектр объекта» (В. Б. Игнатьев): спектр с подписанными лабораторными длинами волн,
красное смещение по линиям (Na D 5892 → 7500 Å даёт z = 0,27), расстояние по закону Хаббла; 2023-F-11-7
«Двойная линия»: положение линии как измеряемая величина. Здесь — эмиссионные линии галактики с малым z:
измерить вершины Hβ и Hα, получить z по двум линиям, v = cz, r = v/H. Модель и валидация —
docs/validation/galaxy_redshift.md.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from astrosim.constants import C
from astrosim.definitions import load_definition, render_content
from astrosim.tasks.base import FieldSpec, KeyEntry, TaskPackage, Verdict, allowed_sigfigs, floor_tolerance, fmt, grade_fields

FAMILY = "galaxy-redshift"
GENERATOR_VERSION = "0.1.0"
FAMILY_LABEL = "спектр галактики → красное смещение → расстояние"
H0_KM_S_MPC = 70.0
C_KM_S = C / 1e3
STEP_A = 2.0                                   # шаг по длине волны, Å
LAMBDA_MIN = 3800.0

# лабораторные длины волн (в воздухе), Å, и относительные интенсивности линий к Hβ
LINES = {
    "Hβ": (4861.3, 1.0),
    "[O III]": (5006.8, 0.5),
    "Hα": (6562.8, 2.86),
    "[N II]": (6583.5, 1.1),
    "[S II] 6717": (6716.4, 0.4),
    "[S II] 6731": (6730.8, 0.3),
}
FWHM_TO_SIGMA = 1 / (2 * math.sqrt(2 * math.log(2)))

FIELDS: list[FieldSpec] = [FieldSpec(**field) for field in load_definition(FAMILY)["answers"]]


def redshift(observed: float, rest: float) -> float:
    return observed / rest - 1


def hubble_distance_mpc(z: float) -> float:
    """r = cz/H при z ≪ 1."""
    return C_KM_S * z / H0_KM_S_MPC


def spectrum(lam: np.ndarray, z: float, f0: float, alpha: float, a_hb: float, fwhm: float) -> np.ndarray:
    """Континуум f0 (λ/5500)^(−α) плюс гауссовы эмиссионные линии, сдвинутые в (1 + z) раз."""
    sig = fwhm * FWHM_TO_SIGMA
    f = f0 * (lam / 5500.0) ** (-alpha)
    for rest, strength in LINES.values():
        f = f + a_hb * strength * np.exp(-0.5 * ((lam - rest * (1 + z)) / sig) ** 2)
    return f


def generate(seed: int) -> TaskPackage:
    rng = np.random.default_rng(seed)
    z = round(float(rng.uniform(0.010, 0.120)), 4)
    f0 = float(rng.integers(20, 61))
    alpha = round(float(rng.uniform(0.0, 1.5)), 2)
    fwhm = float(rng.integers(8, 15))
    a_hb = round(float(rng.uniform(0.6, 1.2)) * f0, 1)
    sigma_n = round(float(rng.uniform(0.02, 0.04)) * f0, 2)

    lam_max = math.ceil((LINES["[S II] 6731"][0] * (1 + z) + 300) / 500) * 500
    lam = np.arange(LAMBDA_MIN, lam_max + STEP_A / 2, STEP_A)
    flux = spectrum(lam, z, f0, alpha, a_hb, fwhm) + rng.normal(0, sigma_n, lam.size)

    f_max = float(flux.max())
    tick_f = next(tk for tk in (5.0, 10.0, 20.0, 50.0, 100.0) if f_max / tk <= 12)
    f_hi = math.ceil(f_max / tick_f) * tick_f
    tick_l = 500.0 if (lam_max - LAMBDA_MIN) / 500 <= 14 else 1000.0

    lam_hb = LINES["Hβ"][0] * (1 + z)
    lam_ha = LINES["Hα"][0] * (1 + z)
    velocity = C_KM_S * z
    distance = hubble_distance_mpc(z)

    # допуск на вершину линии: половина шага сетки плюс участок, где гауссиана лежит выше вершины минус 2σ шума
    sig_line = fwhm * FWHM_TO_SIGMA

    def tol_peak(amplitude: float) -> float:
        return 2 * (STEP_A / 2 + sig_line * math.sqrt(2 * sigma_n / amplitude))

    tol_hb, tol_ha = tol_peak(a_hb), tol_peak(a_hb * LINES["Hα"][1])
    tol_z = 0.5 * math.hypot(tol_hb / LINES["Hβ"][0], tol_ha / LINES["Hα"][0]) + 1e-4     # + округление λ₀ до 1 Å
    tol_v = C_KM_S * tol_z + 0.002 * velocity
    tol_r = tol_v / H0_KM_S_MPC + 0.01 * distance

    designation = f"G {1000 + seed % 9000}"
    lines_text = "Hβ 4861 Å, [O III] 5007 Å, Hα 6563 Å, [N II] 6583 Å, [S II] 6717 и 6731 Å"
    statement = render_content(FAMILY, "statement", {
        'designation': designation,
        'fmt_LAMBDA_MIN_4': fmt(LAMBDA_MIN, 4),
        'fmt_lam_max_4': fmt(lam_max, 4),
        'lines_text': lines_text
    })
    public: dict[str, Any] = {
        "family_label": FAMILY_LABEL,
        "statement": statement,
        "data": {
            "series": [{"id": "F", "label": "спектр", "marker": "line", "points": [[float(x), round(float(y), 2)] for x, y in zip(lam, flux)]}],
            "axes": {"x": {"label": "длина волны, Å", "min": LAMBDA_MIN, "max": float(lam_max), "tick": tick_l},
                     "y": {"label": "F_λ, 10⁻¹⁷ эрг/(см²·с·Å)", "min": 0.0, "max": f_hi, "tick": tick_f}},
        },
        "plot": {"caption": "Спектр галактики", "x": {"key": "λ", "unit": "Å", "decimals": 0},
                 "y": {"key": "F", "unit": "", "decimals": 1, "sign": False}},
        "fields": [f.__dict__ for f in FIELDS],
        "tools": ["cursor", "loupe", "extremum", "segment"],
        "given": {"rest_wavelengths": {k: v[0] for k, v in LINES.items()}, "hubble": H0_KM_S_MPC},
    }
    key = [
        KeyEntry("lambda_hb", lam_hb, 4, floor_tolerance(tol_hb, lam_hb), sigfig_allowed=allowed_sigfigs(tol_hb, lam_hb)),
        KeyEntry("lambda_ha", lam_ha, 4, floor_tolerance(tol_ha, lam_ha), sigfig_allowed=allowed_sigfigs(tol_ha, lam_ha)),
        KeyEntry("z", z, 6, floor_tolerance(tol_z, z), sigfig_allowed=allowed_sigfigs(tol_z, z)),
        KeyEntry("velocity", velocity, 4, floor_tolerance(tol_v, velocity), sigfig_allowed=allowed_sigfigs(tol_v, velocity)),
        KeyEntry("distance", distance, 7, floor_tolerance(tol_r, distance), sigfig_allowed=allowed_sigfigs(tol_r, distance)),
    ]
    lam_o3 = LINES["[O III]"][0] * (1 + z)
    solution = render_content(FAMILY, "solution", {
        'fmt_lam_ha_4': fmt(lam_ha, 4),
        'fmt_lam_hb_4': fmt(lam_hb, 4),
        'fmt_lam_o3_4': fmt(lam_o3, 4),
        'fmt_1_z_4': fmt(1 + z, 4),
        'fmt_redshift_lam_hb_4861_0_3': fmt(redshift(lam_hb, 4861.0), 3),
        'fmt_redshift_lam_ha_6563_0_3': fmt(redshift(lam_ha, 6563.0), 3),
        'fmt_z_3': fmt(z, 3),
        'fmt_velocity_3': fmt(velocity, 3),
        'fmt_distance': fmt(distance)
    })
    private = {
        "truth": {"z": z, "lambda_hb": lam_hb, "lambda_ha": lam_ha, "velocity": velocity, "distance_mpc": distance,
                  "f0": f0, "alpha": alpha, "fwhm": fwhm, "a_hb": a_hb, "sigma_n": sigma_n, "lam_max": lam_max},
        "key": [k.__dict__ for k in key],
        "solution": solution,
    }
    return TaskPackage(FAMILY, GENERATOR_VERSION, seed, public, private)


def grade(package: TaskPackage, answers: dict[str, str]) -> Verdict:
    key = [KeyEntry(**k) for k in package.private["key"]]
    return grade_fields(FIELDS, key, answers)
