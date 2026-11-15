"""Спектрально-двойная с круговыми орбитами (SB2, e = 0): кривые лучевых скоростей и параметры орбиты.

Обозначения и формулы — см. docs/validation/binary_rv.md (там же эталон: Капелла по Torres et al. 2015).

Фаза φ отсчитывается от момента, когда компонент A проходит через γ, удаляясь от наблюдателя:
    v_A(φ) = γ + K_A sin 2πφ,   v_B(φ) = γ − K_B sin 2πφ.
Для круговой орбиты a_A sin i = K_A P / 2π, a sin i = (K_A + K_B) P / 2π, q = M_B / M_A = K_A / K_B,
M_A + M_B = 4π² a³ / (G P²), максимальное угловое расстояние θ_max = a / d = a[а.е.] · π[″] (в квадратуре, не зависит от i).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from astrosim.constants import AU, DAY, G, M_SUN


@dataclass(frozen=True)
class Sb2Circular:
    """Параметры системы: период в сутках, полуамплитуды и γ в км/с, наклон в градусах, параллакс в угловых секундах."""

    period_days: float
    k_a: float
    k_b: float
    gamma: float
    inclination_deg: float
    parallax_arcsec: float

    # ── кривые ──
    def v_a(self, phase: np.ndarray | float) -> np.ndarray:
        return self.gamma + self.k_a * np.sin(2 * np.pi * np.asarray(phase, dtype=float))

    def v_b(self, phase: np.ndarray | float) -> np.ndarray:
        return self.gamma - self.k_b * np.sin(2 * np.pi * np.asarray(phase, dtype=float))

    # ── производные величины (СИ внутри, наружу — привычные единицы) ──
    @property
    def period_s(self) -> float:
        return self.period_days * DAY

    @property
    def a_sin_i_m(self) -> float:
        """Большая полуось относительной орбиты, спроецированная: (K_A + K_B) P / 2π, м."""
        return (self.k_a + self.k_b) * 1e3 * self.period_s / (2 * math.pi)

    @property
    def a_m(self) -> float:
        return self.a_sin_i_m / math.sin(math.radians(self.inclination_deg))

    @property
    def a_au(self) -> float:
        return self.a_m / AU

    @property
    def mass_sum_kg(self) -> float:
        return 4 * math.pi**2 * self.a_m**3 / (G * self.period_s**2)

    @property
    def mass_sum_msun(self) -> float:
        return self.mass_sum_kg / M_SUN

    @property
    def mass_ratio(self) -> float:
        """q = M_B / M_A = K_A / K_B."""
        return self.k_a / self.k_b

    @property
    def mass_a_msun(self) -> float:
        return self.mass_sum_msun * self.k_b / (self.k_a + self.k_b)

    @property
    def mass_b_msun(self) -> float:
        return self.mass_sum_msun * self.k_a / (self.k_a + self.k_b)

    @property
    def theta_max_arcsec(self) -> float:
        """Максимальное угловое расстояние между компонентами: a[а.е.] · π[″] (1 а.е. с 1 пк видна под 1″)."""
        return self.a_au * self.parallax_arcsec


def from_masses(period_days: float, mass_a_msun: float, mass_b_msun: float, inclination_deg: float,
                gamma: float, parallax_arcsec: float) -> Sb2Circular:
    """Обратная задача генератора: по массам и периоду — полуамплитуды (третий закон Кеплера)."""
    period_s = period_days * DAY
    m_tot = (mass_a_msun + mass_b_msun) * M_SUN
    a_m = (G * m_tot * period_s**2 / (4 * math.pi**2)) ** (1 / 3)
    sin_i = math.sin(math.radians(inclination_deg))
    v_rel = 2 * math.pi * a_m / period_s * sin_i / 1e3   # км/с, K_A + K_B
    k_a = v_rel * mass_b_msun / (mass_a_msun + mass_b_msun)
    k_b = v_rel * mass_a_msun / (mass_a_msun + mass_b_msun)
    return Sb2Circular(period_days, k_a, k_b, gamma, inclination_deg, parallax_arcsec)


@dataclass(frozen=True)
class Derived:
    """Производные величины с погрешностями, распространёнными линейно из σ(K_A), σ(K_B)."""

    a_au: float
    a_au_sigma: float
    mass_sum_msun: float
    mass_sum_sigma: float
    theta_max_arcsec: float
    theta_max_sigma: float


def propagate(system: Sb2Circular, sigma_k_a: float, sigma_k_b: float) -> Derived:
    """a ∝ K_A + K_B, M ∝ a³, θ ∝ a (P, i, π считаются точными — они даны в условии)."""
    k_sum = system.k_a + system.k_b
    rel = math.hypot(sigma_k_a, sigma_k_b) / k_sum
    return Derived(
        a_au=system.a_au, a_au_sigma=system.a_au * rel,
        mass_sum_msun=system.mass_sum_msun, mass_sum_sigma=system.mass_sum_msun * 3 * rel,
        theta_max_arcsec=system.theta_max_arcsec, theta_max_sigma=system.theta_max_arcsec * rel,
    )
