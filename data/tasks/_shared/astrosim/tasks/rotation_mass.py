"""Кеплеровская кривая вращения газового диска вокруг точечной массы."""
from __future__ import annotations

import math

import numpy as np

from astrosim.constants import ARCSEC, M_SUN, PC, G
from astrosim.tasks.base import fmt
from astrosim.tasks.observed import assemble, grade  # noqa: F401

FAMILY = "rotation-mass"
GENERATOR_VERSION = "0.1.0"
FAMILY_LABEL = "вращение газового диска → масса центрального объекта"


def mass_solar(radius_pc, velocity_kms):
    return (velocity_kms * 1000) ** 2 * radius_pc * PC / (G * M_SUN)


def generate(seed):
    rng = np.random.default_rng(seed)
    distance = float(rng.integers(12, 31))
    inclination = float(rng.integers(40, 81))
    mass = float(rng.uniform(1e8, 9e8))
    sigma = float(rng.uniform(2, 4))
    theta = np.linspace(0.5, 3.0, 26)
    radius = theta * ARCSEC * distance * 1e6
    speed = np.sqrt(G * mass * M_SUN / (radius * PC)) / 1000
    projected = speed * math.sin(math.radians(inclination))
    v1, v2 = projected + rng.normal(0, sigma, len(theta)), -projected + rng.normal(0, sigma, len(theta))
    ref_radius = ARCSEC * distance * 1e6  # θ = 1″ — один из отсчётов
    ref_speed = math.sqrt(G * mass * M_SUN / (ref_radius * PC)) / 1000
    tol_speed = 3 * sigma / math.sqrt(2) / math.sin(math.radians(inclination))
    # θ и D заданы точно, допуск радиуса — только округление в бланке.
    tol_radius = ref_radius * 0.001
    tol_mass = mass * 2 * tol_speed / ref_speed
    context = {"designation": f"BH {1000 + seed % 9000}", "distance": fmt(distance, 3),
               "inclination": str(int(inclination)), "sigma": fmt(sigma, 2),
               "radius": fmt(ref_radius, 3), "speed": fmt(ref_speed, 3), "mass": fmt(mass / 1e8, 3)}
    lim = math.ceil(float(max(abs(v1).max(), abs(v2).max())) / 100) * 100
    return assemble(FAMILY, GENERATOR_VERSION, seed,
                    series=[{"id": name, "label": label, "marker": marker,
                             "points": [[round(float(x), 2), round(float(y), 2)] for x, y in zip(theta, values)]}
                            for name, label, marker, values in [("A", "удаляющаяся сторона", "dot", v1),
                                                               ("B", "приближающаяся сторона", "ring", v2)]],
                    axes={"x": {"label": "угловое расстояние от центра, ″", "min": 0, "max": 3.2, "tick": 0.5},
                          "y": {"label": "лучевая скорость, км/с", "min": -lim, "max": lim, "tick": 100}},
                    plot={"caption": "Лучевые скорости двух сторон диска относительно центра галактики",
                          "x": {"key": "θ", "unit": "″", "decimals": 2},
                          "y": {"key": "v", "unit": "км/с", "decimals": 1, "sign": True}},
                    given={"distance_mpc": distance, "inclination_deg": inclination, "sigma_kms": sigma},
                    truth={"radius": ref_radius, "speed": ref_speed, "mass": mass / 1e8, "sigma": sigma},
                    tolerances={"radius": tol_radius, "speed": tol_speed, "mass": tol_mass / 1e8},
                    points={"radius": 8, "speed": 7, "mass": 10}, context=context)
