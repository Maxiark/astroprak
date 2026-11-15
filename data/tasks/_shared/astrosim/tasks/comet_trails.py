"""Семейство «снимок со следами звёзд → угловая скорость → скорость кометы» (photo-sphere / image-series-motion).

Прототип: 2026-F-9-9 «Пролетела» (О. Ю. Голубева) — снимок кометы, сложенный по комете, звёзды прочертили
треки; требуется пространственная скорость. Критерий оттуда же: измерение не менее трёх следов даёт полный
балл, один-два — половину (docs/research/format.md §3).

Сцена строится из физики: угловая скорость кометы μ и время экспозиции T задают длину всех следов,
позиционный угол — их направление. Валидация — docs/validation/comet_trails.md.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from astrosim.models.sky_field import parabolic_speed_kms, tangential_velocity_kms, trail_offsets
from astrosim.definitions import load_definition, render_content
from astrosim.tasks.base import FieldSpec, KeyEntry, TaskPackage, Verdict, allowed_sigfigs, floor_tolerance, fmt, grade_fields

FAMILY = "comet-trails"
GENERATOR_VERSION = "0.1.0"
FAMILY_LABEL = "следы звёзд на снимке → скорость кометы"

FIELDS: list[FieldSpec] = [FieldSpec(**field) for field in load_definition(FAMILY)["answers"]]


def generate(seed: int) -> TaskPackage:
    rng = np.random.default_rng(seed)
    # комета вблизи перигелия: 0,4–1,2 а. е. от Солнца, 0,3–1,5 а. е. от Земли
    r_au = round(float(rng.uniform(0.4, 1.2)), 2)
    delta_au = round(float(rng.uniform(0.3, 1.5)), 2)
    hours = float(rng.choice([0.5, 1.0, 1.5, 2.0]))
    v_total = parabolic_speed_kms(r_au)
    # угол между вектором скорости и лучом зрения: от него тангенциальная составляющая
    psi = float(rng.uniform(25.0, 85.0))
    v_t = v_total * math.sin(math.radians(psi))
    # обратная задача: какая угловая скорость даёт такую тангенциальную
    from astrosim.constants import ARCSEC, AU

    mu = v_t * 1e3 * 3600.0 / (delta_au * AU) / ARCSEC          # ″/ч
    position_angle = float(rng.uniform(0.0, 360.0))

    # центр поля и размер кадра: следы должны занимать 5–15 % ширины
    ra_c = round(float(rng.uniform(0.0, 360.0)), 1)
    dec_c = round(float(rng.uniform(-40.0, 60.0)), 1)
    trail_deg = mu * hours / 3600.0
    width_deg = float(np.clip(trail_deg / float(rng.uniform(0.05, 0.15)), 0.5, 12.0))
    tick = next(t for t in (0.1, 0.2, 0.25, 0.5, 1.0, 2.0) if width_deg / t <= 12)
    half = math.ceil(width_deg / 2 / tick) * tick
    cos_dec = math.cos(math.radians(dec_c))

    d_ra, d_dec = trail_offsets(mu / 3600.0, position_angle, hours)
    d_ra /= cos_dec                                              # Δα на небе → Δα по оси прямого восхождения

    n_stars = int(rng.integers(14, 26))
    margin = 0.9
    stars = []
    for _ in range(n_stars):
        ra = ra_c + float(rng.uniform(-half, half)) * margin
        dec = dec_c + float(rng.uniform(-half, half)) * margin
        # следы направлены против движения кометы (кадры сложены по комете)
        stars.append([round(ra, 5), round(dec, 5), round(ra - d_ra, 5), round(dec - d_dec, 5)])

    # концы следа видно на снимке, курсор к ним прилипает: ошибка — доля длины следа плюс округление курсора
    tol_len = max(0.05 * trail_deg, 2e-3)
    tol_mu = tol_len * 3600.0 / hours
    rel = tol_mu / mu
    tol_vt = v_t * rel
    tol_v = v_total * 0.02                                       # округление констант листа
    # ψ = arcsin(v_t / v): dψ = (dv_t/v) / cos ψ
    tol_psi = math.degrees(rel * math.tan(math.radians(psi)) + 0.02 * math.tan(math.radians(psi)))

    designation = f"C/20{24 + seed % 9} {chr(65 + seed % 26)}{1 + seed % 9}"
    statement = render_content(FAMILY, "statement", {
        'designation': designation,
        'fmt_hours_2': fmt(hours, 2),
        'fmt_delta_au_2': fmt(delta_au, 2),
        'fmt_r_au_2': fmt(r_au, 2)
    })
    public: dict[str, Any] = {
        "family_label": FAMILY_LABEL,
        "statement": statement,
        "data": {
            "series": [{"id": "C", "label": "комета", "marker": "dot", "points": [[round(ra_c, 5), round(dec_c, 5)]]}],
            "segments": [{"id": "S", "label": "следы звёзд", "items": stars}],
            "axes": {"x": {"label": "прямое восхождение α, °", "min": round(ra_c - half, 4), "max": round(ra_c + half, 4), "tick": tick, "inverted": True},
                     "y": {"label": "склонение δ, °", "min": round(dec_c - half, 4), "max": round(dec_c + half, 4), "tick": tick}},
            "spherical": True,
        },
        "plot": {"caption": "Снимок: комета неподвижна, звёзды прочертили следы", "x": {"key": "α", "unit": "°", "decimals": 3},
                 "y": {"key": "δ", "unit": "°", "decimals": 3, "sign": False}},
        "fields": [f.__dict__ for f in FIELDS],
        "tools": ["cursor", "loupe", "segment"],
        "given": {"hours": hours, "delta_au": delta_au, "r_au": r_au},
    }
    key = [
        KeyEntry("mu", mu, 7, floor_tolerance(tol_mu, mu), sigfig_allowed=allowed_sigfigs(tol_mu, mu)),
        KeyEntry("v_t", v_t, 6, floor_tolerance(tol_vt, v_t), sigfig_allowed=allowed_sigfigs(tol_vt, v_t)),
        KeyEntry("v", v_total, 6, floor_tolerance(tol_v, v_total), sigfig_allowed=allowed_sigfigs(tol_v, v_total)),
        KeyEntry("angle", psi, 6, floor_tolerance(tol_psi, psi), sigfig_allowed=allowed_sigfigs(tol_psi, psi)),
    ]
    solution = render_content(FAMILY, "solution", {
        'fmt_trail_deg_3': fmt(trail_deg, 3),
        'fmt_trail_deg_3600_3': fmt(trail_deg * 3600, 3),
        'fmt_cos_dec_3': fmt(cos_dec, 3),
        'fmt_mu_3': fmt(mu, 3),
        'fmt_tangential_velocity_kms_1_0_1_0_3': fmt(tangential_velocity_kms(1.0, 1.0), 3),
        'fmt_v_t_3': fmt(v_t, 3),
        'fmt_r_au_2': fmt(r_au, 2),
        'fmt_v_total_3': fmt(v_total, 3),
        'fmt_v_t_v_total_3': fmt(v_t / v_total, 3),
        'fmt_psi_3': fmt(psi, 3),
        'fmt_v_total_math_cos_math_radians_psi_3': fmt(v_total * math.cos(math.radians(psi)), 3)
    })
    private = {
        "truth": {"mu": mu, "v_t": v_t, "v": v_total, "angle": psi, "r_au": r_au, "delta_au": delta_au,
                  "hours": hours, "trail_deg": trail_deg, "position_angle": position_angle, "cos_dec": cos_dec,
                  "n_stars": n_stars, "tick": tick},
        "key": [k.__dict__ for k in key],
        "solution": solution,
    }
    return TaskPackage(FAMILY, GENERATOR_VERSION, seed, public, private)


def grade(package: TaskPackage, answers: dict[str, str]) -> Verdict:
    key = [KeyEntry(**k) for k in package.private["key"]]
    return grade_fields(FIELDS, key, answers)
