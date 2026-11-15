"""Диаграмма Хаббла: наклон, характерное время расширения и расстояние."""
from __future__ import annotations

import math

import numpy as np

from astrosim.constants import PC, YEAR_TROPICAL
from astrosim.tasks.base import fmt
from astrosim.tasks.observed import assemble, grade  # noqa: F401

FAMILY = "hubble-diagram"
GENERATOR_VERSION = "0.1.0"
FAMILY_LABEL = "диаграмма Хаббла → темп и характерное время расширения"


def hubble_time_gyr(hubble):
    return PC * 1e6 / 1000 / hubble / YEAR_TROPICAL / 1e9


def generate(seed):
    rng = np.random.default_rng(seed)
    hubble = float(rng.uniform(60, 85))
    sigma = float(rng.uniform(80, 160))
    distances = np.linspace(10, 120, 23)
    velocities = hubble * distances + rng.normal(0, sigma, len(distances))
    query_v = float(rng.integers(30, 65) * 100)
    time = hubble_time_gyr(hubble)
    distance = query_v / hubble
    tol_h = 3 * sigma / float(max(distances))
    context = {"designation": f"HD {1000 + seed % 9000}", "sigma": fmt(sigma, 3),
               "query_velocity": str(int(query_v)), "hubble": fmt(hubble, 3),
               "time": fmt(time, 3), "distance": fmt(distance, 3)}
    return assemble(FAMILY, GENERATOR_VERSION, seed,
                    series=[{"id": "galaxies", "label": "галактики", "marker": "dot",
                             "points": [[float(d), round(float(v), 1)] for d, v in zip(distances, velocities)]}],
                    axes={"x": {"label": "расстояние, Мпк", "min": 0, "max": 125, "tick": 20},
                          "y": {"label": "скорость удаления, км/с", "min": 0,
                                "max": math.ceil(float(max(velocities)) / 2000) * 2000, "tick": 2000}},
                    plot={"caption": "Скорости удаления и независимо измеренные расстояния",
                          "x": {"key": "d", "unit": "Мпк", "decimals": 1},
                          "y": {"key": "v", "unit": "км/с", "decimals": 0, "sign": False}},
                    given={"sigma_kms": sigma, "query_velocity_kms": query_v},
                    truth={"hubble": hubble, "time": time, "distance": distance, "sigma": sigma},
                    tolerances={"hubble": tol_h, "time": time * tol_h / hubble, "distance": distance * tol_h / hubble},
                    points={"hubble": 10, "time": 7, "distance": 8}, context=context)
