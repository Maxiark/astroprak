"""Поле неба с экваториальной сеткой: угловые расстояния, следы звёзд при сложении кадров по движущемуся объекту.

Прототип: 2026-F-9-9 «Пролетела» (снимок кометы, сложенный по комете; звёзды прочертили треки).
Валидация — docs/validation/comet_trails.md.

Соглашения: прямое восхождение α и склонение δ в градусах; на снимке α растёт влево (астрономическая
ориентация), поэтому ось α выводится перевёрнутой. Угловое расстояние между близкими точками —
малоугловое приближение с косинусом склонения:
    Δθ² = (Δα cos δ)² + (Δδ)².
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def angular_separation_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Точное расстояние по формуле гаверсинусов (используется для проверки малоуглового приближения)."""
    p1, p2 = math.radians(dec1), math.radians(dec2)
    dl = math.radians(ra2 - ra1)
    dp = p2 - p1
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a))))


def small_angle_separation_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Малоугловое приближение: то, что участник считает линейкой по осям снимка."""
    dec_mid = math.radians((dec1 + dec2) / 2)
    return math.hypot((ra2 - ra1) * math.cos(dec_mid), dec2 - dec1)


@dataclass(frozen=True)
class Trail:
    """След звезды: отрезок от начала экспозиции к концу, в координатах снимка (α, δ) в градусах."""

    ra1: float
    dec1: float
    ra2: float
    dec2: float

    @property
    def length_deg(self) -> float:
        return small_angle_separation_deg(self.ra1, self.dec1, self.ra2, self.dec2)


def trail_offsets(mu_deg_per_hour: float, position_angle_deg: float, hours: float) -> tuple[float, float]:
    """Смещение следа за время экспозиции.

    Кадры сложены по движущемуся объекту, поэтому звёзды смещаются на столько же, сколько объект,
    но в противоположную сторону. Позиционный угол отсчитывается от направления на север (+δ)
    к востоку (+α), как принято для собственных движений.

    Возвращает (Δα, Δδ) в градусах — до деления Δα на cos δ, которое делает вызывающий код.
    """
    total = mu_deg_per_hour * hours
    pa = math.radians(position_angle_deg)
    return total * math.sin(pa), total * math.cos(pa)


def tangential_velocity_kms(mu_arcsec_per_hour: float, distance_au: float) -> float:
    """v_t = μ Δ. При μ в ″/ч и Δ в а. е.: 1″ на 1 а. е. = 1 а. е. · 4,848·10⁻⁶ рад."""
    from astrosim.constants import ARCSEC, AU

    return mu_arcsec_per_hour * ARCSEC * distance_au * AU / 3600.0 / 1e3


def parabolic_speed_kms(r_au: float) -> float:
    """Скорость на параболической орбите: v = sqrt(2 G M☉ / r)."""
    from astrosim.constants import AU, G, M_SUN

    return math.sqrt(2 * G * M_SUN / (r_au * AU)) / 1e3
