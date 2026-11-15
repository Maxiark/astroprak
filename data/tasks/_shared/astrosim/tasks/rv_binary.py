"""Семейство «кривые лучевых скоростей двойной → параметры орбиты» (curve-reading / orbit-from-positions).

Прототипы в архиве: 2026-R-10-10 «Капелла», 2023-F-11-7 «Двойная линия» (content/taxonomy.yaml).
seed → параметры системы → набор точек с шумом → условие, поля бланка, ключ с допусками, эталонное решение.
Один и тот же seed при одной версии генератора даёт байт-в-байт тот же пакет.

Допуски (гипотеза, калибруется по журналу событий, см. docs/validation/binary_rv.md §4):
    tol(K) = 2σ_v + tick/10 — два «сигма» шума плюс точность чтения оси;
    tol(a)/a = tol(θ)/θ = sqrt(tol²(K_A) + tol²(K_B)) / (K_A + K_B),  tol(M)/M = 3 · tol(a)/a;
    эталонная погрешность для поля «θ ± δθ» — tol(θ)/2.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from astrosim.analysis.sinefit import fit_sine
from astrosim.models.binary_rv import Sb2Circular, from_masses
from astrosim.definitions import load_definition, render_content
from astrosim.tasks.base import FieldSpec, KeyEntry, TaskPackage, Verdict, allowed_sigfigs, floor_tolerance, fmt, grade_fields

FAMILY = "rv-binary"
GENERATOR_VERSION = "0.1.0"
FAMILY_LABEL = "кривые лучевых скоростей → параметры орбиты"
LAMBDA_VIS_M = 550e-9

FIELDS: list[FieldSpec] = [FieldSpec(**field) for field in load_definition(FAMILY)["answers"]]


def _draw_system(rng: np.random.Generator) -> tuple[Sb2Circular, dict[str, float]]:
    """Физически осмысленные системы: массы 0,8–4 M☉, q 0,5–1, P 2–400 сут, i 30–80°, π 5–100 мсд."""
    for _ in range(100):
        mass_a = float(rng.uniform(0.8, 4.0))
        q = float(rng.uniform(0.5, 1.0))
        period = float(np.exp(rng.uniform(np.log(2.0), np.log(400.0))))
        incl = float(rng.uniform(30.0, 80.0))
        parallax = float(np.exp(rng.uniform(np.log(0.005), np.log(0.100))))
        gamma = float(rng.uniform(-60.0, 60.0))
        system = from_masses(period, mass_a, mass_a * q, incl, gamma, parallax)
        if 5.0 <= system.k_a <= 150.0 and 5.0 <= system.k_b <= 150.0:
            return system, {"mass_a": mass_a, "mass_b": mass_a * q}
    raise RuntimeError("не удалось подобрать систему")  # практически недостижимо


def _nice_bounds(lo: float, hi: float, tick: float) -> tuple[float, float]:
    return math.floor((lo - tick / 2) / tick) * tick, math.ceil((hi + tick / 2) / tick) * tick


def generate(seed: int) -> TaskPackage:
    rng = np.random.default_rng(seed)
    system, masses = _draw_system(rng)
    # округляем «данные условия» до того, что печатается: они и есть истина для участника
    period = round(system.period_days, 2)
    incl = round(system.inclination_deg)
    parallax = round(system.parallax_arcsec, 3)
    system = Sb2Circular(period, system.k_a, system.k_b, round(system.gamma, 1), incl, parallax)

    k_scale = (system.k_a + system.k_b) / 2
    sigma_v = max(0.3, float(rng.uniform(0.02, 0.05)) * k_scale)
    n_a, n_b = int(rng.integers(30, 46)), int(rng.integers(30, 46))
    phase_a = np.sort(rng.uniform(0, 1, n_a))
    phase_b = np.sort(rng.uniform(0, 1, n_b))
    v_a = system.v_a(phase_a) + rng.normal(0, sigma_v, n_a)
    v_b = system.v_b(phase_b) + rng.normal(0, sigma_v, n_b)

    k_max = max(system.k_a, system.k_b)
    span = 2 * k_max + 6 * sigma_v
    tick = next(t for t in (1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0) if span / t <= 14)   # 7–14 делений по оси скоростей
    y_lo, y_hi = _nice_bounds(system.gamma - k_max - 3 * sigma_v, system.gamma + k_max + 3 * sigma_v, tick)

    seeing = float(rng.choice([0.5, 0.7, 1.0, 1.5, 2.0]))
    aperture = float(rng.choice([0.5, 1.0, 2.5, 6.0]))
    diffraction = 1.22 * LAMBDA_VIS_M / aperture / 4.848e-6   # ″
    limit = max(seeing, diffraction)
    resolvable = system.theta_max_arcsec >= limit

    # допуски
    tol_k = 2 * sigma_v + tick / 10
    rel = math.sqrt(2) * tol_k / (system.k_a + system.k_b)
    tol_a, tol_m, tol_theta = system.a_au * rel, system.mass_sum_msun * 3 * rel, system.theta_max_arcsec * rel

    tol_k_a, tol_k_b = floor_tolerance(tol_k, system.k_a), floor_tolerance(tol_k, system.k_b)
    tol_a, tol_m = floor_tolerance(tol_a, system.a_au), floor_tolerance(tol_m, system.mass_sum_msun)
    tol_theta = floor_tolerance(tol_theta, system.theta_max_arcsec)

    # эталонное решение по подгонке к тем же данным (что вообще можно извлечь при таком шуме)
    fit_a, fit_b = fit_sine(phase_a, v_a, +1), fit_sine(phase_b, v_b, -1)

    designation = f"AS {1000 + seed % 9000}"
    statement = render_content(FAMILY, "statement", {
        'designation': designation,
        'fmt_period_5': fmt(period, 5),
        'incl': incl,
        'fmt_parallax_2': fmt(parallax, 2),
        'fmt_aperture_2': fmt(aperture, 2),
        'fmt_seeing_2': fmt(seeing, 2)
    })
    data = {
        "series": [
            {"id": "A", "label": "компонент A", "marker": "dot", "points": [[round(float(p), 4), round(float(v), 2)] for p, v in zip(phase_a, v_a)]},
            {"id": "B", "label": "компонент B", "marker": "ring", "points": [[round(float(p), 4), round(float(v), 2)] for p, v in zip(phase_b, v_b)]},
        ],
        "axes": {"x": {"label": "фаза, доля периода", "min": 0.0, "max": 1.0, "tick": 0.1},
                 "y": {"label": "v, км/с", "min": y_lo, "max": y_hi, "tick": tick}},
    }
    public: dict[str, Any] = {
        "family_label": FAMILY_LABEL,
        "statement": statement, "data": data,
        "plot": {"caption": "Лучевые скорости компонент от фазы", "x": {"key": "φ", "unit": "", "decimals": 2}, "y": {"key": "v", "unit": "км/с", "decimals": 1, "sign": True}},
        "fields": [f.__dict__ for f in FIELDS],
        "tools": ["cursor", "loupe", "extremum", "segment"],
        "given": {"period_days": period, "inclination_deg": incl, "parallax_arcsec": parallax, "seeing_arcsec": seeing, "aperture_m": aperture},
    }
    key = [
        KeyEntry("k_a", system.k_a, 3, tol_k_a, sigfig_allowed=allowed_sigfigs(tol_k, system.k_a)),
        KeyEntry("k_b", system.k_b, 3, tol_k_b, sigfig_allowed=allowed_sigfigs(tol_k, system.k_b)),
        KeyEntry("a_au", system.a_au, 5, tol_a, sigfig_allowed=allowed_sigfigs(tol_a, system.a_au)),
        KeyEntry("mass_sum", system.mass_sum_msun, 5, tol_m, sigfig_allowed=allowed_sigfigs(tol_m, system.mass_sum_msun)),
        KeyEntry("theta_max", system.theta_max_arcsec, 4, tol_theta, sigma=tol_theta / 2, points_error=2,
                 sigfig_allowed=allowed_sigfigs(tol_theta, system.theta_max_arcsec)),
        KeyEntry("resolvable", "да" if resolvable else "нет", 3),
    ]
    solution = render_content(FAMILY, "solution", {
        'fmt_system_k_a': fmt(system.k_a),
        'fmt_system_k_b': fmt(system.k_b),
        'fmt_system_gamma': fmt(system.gamma),
        'fmt_fit_a_amplitude_3': fmt(fit_a.amplitude, 3),
        'fmt_fit_a_amplitude_sigma_1': fmt(fit_a.amplitude_sigma, 1),
        'fmt_fit_b_amplitude_3': fmt(fit_b.amplitude, 3),
        'fmt_fit_b_amplitude_sigma_1': fmt(fit_b.amplitude_sigma, 1),
        'fmt_system_a_sin_i_m_1000_0_3': fmt(system.a_sin_i_m / 1000.0, 3),
        'incl': incl,
        'fmt_system_a_m_1000_0_3': fmt(system.a_m / 1000.0, 3),
        'fmt_system_a_au': fmt(system.a_au),
        'fmt_system_mass_sum_kg_3': fmt(system.mass_sum_kg, 3),
        'fmt_system_mass_sum_msun': fmt(system.mass_sum_msun),
        'fmt_system_mass_ratio': fmt(system.mass_ratio),
        'fmt_system_mass_a_msun': fmt(system.mass_a_msun),
        'fmt_system_mass_b_msun': fmt(system.mass_b_msun),
        'fmt_parallax_2': fmt(parallax, 2),
        'fmt_system_theta_max_arcsec': fmt(system.theta_max_arcsec),
        'fmt_rel_2': fmt(rel / 2),
        'fmt_tol_theta_2_1': fmt(tol_theta / 2, 1),
        'fmt_diffraction': fmt(diffraction),
        'fmt_seeing_2': fmt(seeing, 2),
        'fmt_limit': fmt(limit),
        'if_resolvable_else': '≥' if resolvable else '<',
        'if_resolvable_else24': 'разрешима' if resolvable else 'не разрешима'
    })
    private = {
        "truth": {"period_days": period, "k_a": system.k_a, "k_b": system.k_b, "gamma": system.gamma, "inclination_deg": incl,
                  "parallax_arcsec": parallax, "sigma_v": sigma_v, "mass_a": masses["mass_a"], "mass_b": masses["mass_b"],
                  "a_au": system.a_au, "mass_sum": system.mass_sum_msun, "theta_max": system.theta_max_arcsec,
                  "resolution_limit": limit},
        "key": [k.__dict__ for k in key],
        "solution": solution,
    }
    return TaskPackage(FAMILY, GENERATOR_VERSION, seed, public, private)


def grade(package: TaskPackage, answers: dict[str, str]) -> Verdict:
    key = [KeyEntry(**k) for k in package.private["key"]]
    return grade_fields(FIELDS, key, answers)
