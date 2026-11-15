"""Одномерная астрометрия: годичный параллакс и собственное движение."""
from __future__ import annotations

import math

import numpy as np

from astrosim.constants import AU, YEAR_TROPICAL
from astrosim.tasks.base import fmt
from astrosim.tasks.observed import assemble, grade  # noqa: F401

FAMILY = "parallax-motion"
GENERATOR_VERSION = "0.1.0"
FAMILY_LABEL = "годичный параллакс и собственное движение → расстояние и скорость"


def position(t, offset, mu, parallax):
    return offset + mu * t + parallax * np.cos(2 * math.pi * t)


def tangential_speed(mu, parallax):
    return AU / YEAR_TROPICAL / 1000 * mu / parallax


def generate(seed):
    rng = np.random.default_rng(seed)
    parallax = float(rng.uniform(0.05, 0.15))
    mu = float(rng.uniform(0.08, 0.3))
    sigma = float(rng.uniform(0.001, 0.002))
    offset = float(rng.uniform(-0.03, 0.03))
    time = np.linspace(0, 2, 81)
    values = position(time, offset, mu, parallax) + rng.normal(0, sigma, len(time))
    distance = 1 / parallax
    speed = tangential_speed(mu, parallax)
    # μ=(x(2)-x(0))/2; π=(x(0)+x(1)-2x(0.5))/4. Допуски — 3σ оценок.
    tol_mu = 3 * sigma / math.sqrt(2)
    tol_pi = 3 * math.sqrt(6) * sigma / 4
    tol_d = distance * tol_pi / parallax
    # Консервативная сумма учитывает корреляцию оценок μ и π.
    tol_v = speed * (tol_mu / mu + tol_pi / parallax)
    context = {"designation": f"PX {1000 + seed % 9000}", "sigma": fmt(sigma, 2),
               "mu": fmt(mu, 3), "parallax": fmt(parallax, 3), "distance": fmt(distance, 3), "speed": fmt(speed, 3)}
    return assemble(FAMILY, GENERATOR_VERSION, seed,
                    series=[{"id": "x", "label": "координата", "marker": "dot",
                             "points": [[round(float(t), 3), round(float(x), 5)] for t, x in zip(time, values)]}],
                    axes={"x": {"label": "время, годы", "min": 0, "max": 2, "tick": 0.25},
                          "y": {"label": "смещение, угл. с", "min": math.floor(float(min(values)) * 10) / 10,
                                "max": math.ceil(float(max(values)) * 10) / 10, "tick": 0.1}},
                    plot={"caption": "Положение звезды в течение двух лет",
                          "x": {"key": "t", "unit": "год", "decimals": 3},
                          "y": {"key": "x", "unit": "″", "decimals": 3, "sign": True}},
                    given={"sigma_arcsec": sigma},
                    truth={"proper_motion": mu, "parallax": parallax, "distance": distance, "speed": speed,
                           "sigma": sigma, "offset": offset},
                    tolerances={"proper_motion": tol_mu, "parallax": tol_pi, "distance": tol_d, "speed": tol_v},
                    points={"proper_motion": 6, "parallax": 6, "distance": 6, "speed": 7}, context=context)
