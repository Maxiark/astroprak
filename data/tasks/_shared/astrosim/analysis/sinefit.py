"""Подгонка синусоиды известного периода методом наименьших квадратов: v(φ) = γ + K sin 2πφ + L cos 2πφ.

Линейная задача по (γ, K, L); ковариация — из остатков (σ² (XᵀX)⁻¹). Используется для эталонного решения
и для оценки σ(K): это то, что в принципе можно вытащить из данных с таким шумом — нижняя граница
разумной погрешности участника.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SineFit:
    gamma: float
    amplitude: float          # |K| с учётом фазового сдвига: sqrt(K² + L²)
    amplitude_sigma: float
    gamma_sigma: float
    residual_sigma: float     # оценка σ шума по остаткам
    n: int


def fit_sine(phase: np.ndarray, v: np.ndarray, sign: float = 1.0) -> SineFit:
    """sign = +1 для компонента A (v = γ + K sin), −1 для B (v = γ − K sin); амплитуда возвращается положительной."""
    phase = np.asarray(phase, dtype=float)
    v = np.asarray(v, dtype=float)
    x = np.column_stack([np.ones_like(phase), sign * np.sin(2 * np.pi * phase), np.cos(2 * np.pi * phase)])
    beta, *_ = np.linalg.lstsq(x, v, rcond=None)
    resid = v - x @ beta
    dof = max(len(v) - 3, 1)
    s2 = float(resid @ resid / dof)
    cov = s2 * np.linalg.inv(x.T @ x)
    k, l = beta[1], beta[2]
    amp = float(np.hypot(k, l))
    # σ амплитуды: градиент (k/amp, l/amp) по ковариации (k, l)
    grad = np.array([k / amp, l / amp]) if amp > 0 else np.array([1.0, 0.0])
    amp_sigma = float(np.sqrt(grad @ cov[1:, 1:] @ grad))
    return SineFit(gamma=float(beta[0]), amplitude=amp, amplitude_sigma=amp_sigma,
                   gamma_sigma=float(np.sqrt(cov[0, 0])), residual_sigma=float(np.sqrt(s2)), n=len(v))
