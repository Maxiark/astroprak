import math
import random
from typing import Any

DR_STEP = 0.03
N_RINGS = 5
R_MAX = DR_STEP * N_RINGS  # 0.15°
AREA_UNIT = DR_STEP * DR_STEP


def _ring_tolerance(count: int) -> int:
    """Допуск ±10% на подсчёт звёзд в кольце (минимум ±2 звезды)."""
    return max(2, math.ceil(0.10 * count))


def _count_rings_and_densities(
    stars: list[dict[str, float]],
    center_a: float,
    center_d: float,
    cos_d: float,
    dr: float = DR_STEP,
    n_rings: int = N_RINGS,
) -> tuple[list[int], list[float]]:
    """Единая функция подсчёта населённости колец и поверхностных плотностей."""
    counts = [0] * n_rings
    for s in stars:
        dx = (s["alpha"] - center_a) * cos_d
        dy = s["delta"] - center_d
        r = math.hypot(dx, dy)
        idx = int((r + 1e-9) / dr)
        if 0 <= idx < n_rings:
            counts[idx] += 1

    densities = []
    for k in range(n_rings):
        r_inner = k * dr
        r_outer = (k + 1) * dr
        ring_area = math.pi * (r_outer**2 - r_inner**2)
        dens = round(counts[k] * (AREA_UNIT / ring_area), 2)
        densities.append(dens)

    return counts, densities


def _compute_truth(seed: int | None = None) -> dict[str, Any]:
    rng = random.Random(seed)

    alpha_0 = round(rng.uniform(14.72, 14.78), 3)
    delta_0 = round(rng.uniform(-72.22, -72.16), 3)

    # Истинное смещение ядра скопления
    alpha_core = round(alpha_0 + rng.uniform(-0.010, 0.010), 3)
    delta_core = round(delta_0 + rng.uniform(-0.010, 0.010), 3)

    # Параметры скопления по задаче S.1.2 Праководства
    rc_true = round(rng.uniform(0.028, 0.036), 3)
    n_cluster = 125
    n_field = 25

    cos_d = math.cos(math.radians(delta_0))
    stars: list[dict[str, float]] = []

    ln_term = math.log(1.0 + (R_MAX / rc_true) ** 2)

    def _is_valid_star(a_cand: float, d_cand: float, target_ring: int, min_sep: float) -> bool:
        dx = (a_cand - alpha_core) * cos_d
        dy = d_cand - delta_core
        r = math.hypot(dx, dy)
        if r >= R_MAX - 0.0015:
            return False
        if int((r + 1e-9) / DR_STEP) != target_ring:
            return False
        for k in range(1, N_RINGS + 1):
            if abs(r - k * DR_STEP) < 0.0013:
                return False
        for prev in stars:
            pdx = (a_cand - prev["alpha"]) * cos_d
            pdy = d_cand - prev["delta"]
            if math.hypot(pdx, pdy) < min_sep:
                return False
        return True

    total_stars = n_cluster + n_field
    for i in range(total_stars):
        if i < n_cluster:
            u = rng.random()
            r_base = rc_true * math.sqrt(math.exp(u * ln_term) - 1.0)
        else:
            r_base = math.sqrt(rng.uniform(0.0, R_MAX**2))

        target_ring = min(int(r_base / DR_STEP), N_RINGS - 1)
        r_lo = target_ring * DR_STEP + (0.0020 if target_ring == 0 else 0.0015)
        r_hi = (target_ring + 1) * DR_STEP - 0.0015

        placed = False
        for attempt in range(220):
            r_try = max(r_lo, min(r_hi, r_base if attempt == 0 else rng.uniform(r_lo, r_hi)))
            theta = rng.uniform(0.0, 2.0 * math.pi)
            dx = r_try * math.cos(theta)
            dy = r_try * math.sin(theta)
            a_star = round(alpha_core + (dx / cos_d), 3)
            d_star = round(delta_core + dy, 3)

            min_sep = 0.0042 if attempt < 70 else (0.0032 if attempt < 150 else 0.0022)
            if _is_valid_star(a_star, d_star, target_ring, min_sep):
                stars.append({"alpha": a_star, "delta": d_star})
                placed = True
                break

        if not placed:
            theta = rng.uniform(0.0, 2.0 * math.pi)
            r_fallback = 0.5 * (r_lo + r_hi)
            a_star = round(alpha_core + (r_fallback * math.cos(theta) / cos_d), 3)
            d_star = round(delta_core + r_fallback * math.sin(theta), 3)
            stars.append({"alpha": a_star, "delta": d_star})

    rng.shuffle(stars)

    true_ring_counts, ring_densities = _count_rings_and_densities(
        stars, alpha_core, delta_core, cos_d
    )

    r_bin1 = DR_STEP
    integral_factor = (rc_true**2 / r_bin1**2) * math.log(1.0 + (r_bin1 / rc_true) ** 2)
    n0_true = round(ring_densities[0] / max(integral_factor, 0.5), 1)

    return {
        "alpha_0": alpha_0,
        "delta_0": delta_0,
        "alpha_core": alpha_core,
        "delta_core": delta_core,
        "rc_true": rc_true,
        "n0_true": n0_true,
        "stars": stars,
        "ring_dr": DR_STEP,
        "true_counts": true_ring_counts,
        "true_densities": ring_densities,
    }


def generate(seed: int | None = None) -> dict:
    actual_seed = seed if seed is not None else 42
    truth = _compute_truth(actual_seed)

    statement_text = (
        "В таблице приведены координаты звёзд некоторого рассеянного скопления (N = 150). "
        "Определите центр скопления, постройте гистограмму радиального распределения плотности звёзд "
        "в концентрических кольцах с шагом 0.03° (с нормировкой на площадку 0.03° × 0.03°), "
        "выберите аналитическую модель профиля и оцените параметры распределения скопления."
    )

    return {
        "id": "radial-cluster",
        "title": "Распределяй и властвуй: Радиальное распределение скопления",
        "max_score": 5.0,
        "entry_point": "widget.html",
        "data": {
            "statement": statement_text,
            "stars": truth["stars"],
            "alpha_0": truth["alpha_0"],
            "delta_0": truth["delta_0"],
            "alpha_core": truth["alpha_core"],
            "delta_core": truth["delta_core"],
            "rc_model": truth["rc_true"],
            "n0_model": truth["n0_true"],
            "ring_dr": truth["ring_dr"],
            "true_counts": truth["true_counts"],
            "true_densities": truth["true_densities"],
        },
        "schema": {
            "fields": [
                {"id": "center_alpha", "kind": "number", "label": "Прямое восхождение центра α*", "unit": "°"},
                {"id": "center_delta", "kind": "number", "label": "Склонение центра δ*", "unit": "°"},
                {
                    "id": "model_type",
                    "kind": "choice",
                    "label": "Модель профиля плотности",
                    "options": [
                        "Профиль Кинга: n(r) = n0 / (1 + (r / rc)^2)",
                        "Экспоненциальный диск: n(r) = n0 * exp(-r / rc)",
                        "Гауссов профиль: n(r) = n0 * exp(-r^2 / (2 rc^2))",
                        "Равномерное ядро: n(r) = n0 при r <= rc",
                        "Степенной спад: n(r) = n0 / (1 + r / rc)^3",
                    ],
                },
                {"id": "rc_val", "kind": "number", "label": "Радиус ядра rc", "unit": "°"},
                {"id": "n0_val", "kind": "number", "label": "Центральная плотность n0", "unit": "зв / (0.03°)²"},
            ]
        },
    }


def grade(seed: int, answers: dict) -> dict:
    try:
        truth = _compute_truth(seed)
    except Exception:
        return {"score": 0.0, "max_score": 5.0, "details": {}}

    answers = answers or {}
    total_score = 0.0
    details = {}

    cos_d0 = math.cos(math.radians(truth["delta_0"]))

    # 1. Центр скопления (1 балл: угловое расстояние до ядра <= 0.020°)
    raw_a = answers.get("center_alpha")
    raw_d = answers.get("center_delta")
    center_ok = False
    dist_deg = None
    ua = None
    ud = None
    user_center_str = "не задан"

    try:
        ua = float(str(raw_a).replace(",", ".").strip())
        ud = float(str(raw_d).replace(",", ".").strip())
        user_center_str = f"({ua:.3f}°, {ud:.3f}°)"
        dx = (ua - truth["alpha_core"]) * cos_d0
        dy = ud - truth["delta_core"]
        dist_deg = round(math.hypot(dx, dy), 4)
        if dist_deg <= 0.020:
            center_ok = True
    except (ValueError, TypeError):
        pass

    score_center = 1.0 if center_ok else 0.0
    total_score += score_center
    details["center_pos"] = {
        "user": user_center_str,
        "truth": f"({truth['alpha_core']}°, {truth['delta_core']}°)",
        "tol": 0.020,
        "score": score_center,
        "max": 1.0,
        "ok": center_ok,
    }

    # 2. Подсчет населенности 5 колец (1 балл: допуск ±10% в каждом кольце, минимум ±2 шт)
    user_counts = answers.get("user_counts")
    counts_ok = False
    max_diff = None
    ref_counts = truth["true_counts"]
    user_center_densities = truth["true_densities"]

    if ua is not None and ud is not None and math.isfinite(ua) and math.isfinite(ud):
        uc_counts, uc_dens = _count_rings_and_densities(truth["stars"], ua, ud, cos_d0)
        user_center_densities = uc_dens
    else:
        uc_counts = truth["true_counts"]

    if isinstance(user_counts, list) and len(user_counts) == N_RINGS:
        parsed_uc = []
        for i in range(N_RINGS):
            try:
                parsed_uc.append(int(user_counts[i]))
            except (ValueError, TypeError):
                parsed_uc.append(0)

        ok_core = all(
            abs(parsed_uc[i] - truth["true_counts"][i]) <= _ring_tolerance(truth["true_counts"][i])
            for i in range(N_RINGS)
        )
        ok_uc = all(
            abs(parsed_uc[i] - uc_counts[i]) <= _ring_tolerance(uc_counts[i])
            for i in range(N_RINGS)
        )

        diff_core = max(abs(parsed_uc[i] - truth["true_counts"][i]) for i in range(N_RINGS))
        diff_uc = max(abs(parsed_uc[i] - uc_counts[i]) for i in range(N_RINGS))

        if ok_uc or (not ok_core and diff_uc <= diff_core):
            counts_ok = ok_uc
            max_diff = diff_uc
            ref_counts = uc_counts
        else:
            counts_ok = ok_core
            max_diff = diff_core
            ref_counts = truth["true_counts"]

    score_counts = 1.0 if counts_ok else 0.0
    total_score += score_counts
    details["bin_counts"] = {
        "user": f"{user_counts} (макс. расхождение {max_diff} шт)" if max_diff is not None else "нет данных",
        "truth": f"{ref_counts}",
        "tol": "±10% (мин. ±2 шт)",
        "score": score_counts,
        "max": 1.0,
        "ok": counts_ok,
    }

    # 3. Тип профиля (1 балл: Профиль Кинга)
    model_raw = str(answers.get("model_type", "")).strip().lower()
    model_ok = ("кинг" in model_raw) or (model_raw == "king")
    score_model = 1.0 if model_ok else 0.0
    total_score += score_model
    details["model_type"] = {
        "user": answers.get("model_type"),
        "truth": "Профиль Кинга",
        "tol": 0,
        "score": score_model,
        "max": 1.0,
        "ok": model_ok,
    }

    # 4. Радиус ядра rc (1 балл, относительная погрешность <= 10%)
    raw_rc = answers.get("rc_val")
    rc_ok = False
    user_rc = None
    rc_true = truth["rc_true"]
    rc_tol = round(max(rc_true * 0.10, 0.003), 4)
    try:
        user_rc = float(str(raw_rc).replace(",", ".").strip())
        if abs(user_rc - rc_true) <= rc_tol + 1e-6:
            rc_ok = True
    except (ValueError, TypeError):
        pass

    score_rc = 1.0 if rc_ok else 0.0
    total_score += score_rc
    details["rc_val"] = {
        "user": user_rc,
        "truth": rc_true,
        "tol": rc_tol,
        "score": score_rc,
        "max": 1.0,
        "ok": rc_ok,
    }

    # 5. Центральная плотность n0 (1 балл, относительная погрешность <= 10%)
    raw_n0 = answers.get("n0_val")
    n0_ok = False
    user_n0 = None
    n0_true = truth["n0_true"]
    r_bin1 = DR_STEP
    integral_factor = (rc_true**2 / r_bin1**2) * math.log(1.0 + (r_bin1 / rc_true) ** 2)
    n0_from_user_center = round(user_center_densities[0] / max(integral_factor, 0.5), 1)
    n0_tol = round(max(n0_true * 0.10, 1.0), 1)
    try:
        user_n0 = float(str(raw_n0).replace(",", ".").strip())
        if (
            abs(user_n0 - n0_true) <= n0_tol + 1e-6
            or (center_ok and abs(user_n0 - n0_from_user_center) <= n0_tol + 1e-6)
        ):
            n0_ok = True
    except (ValueError, TypeError):
        pass

    score_n0 = 1.0 if n0_ok else 0.0
    total_score += score_n0
    details["n0_val"] = {
        "user": user_n0,
        "truth": n0_true,
        "tol": n0_tol,
        "score": score_n0,
        "max": 1.0,
        "ok": n0_ok,
    }

    return {
        "score": round(total_score, 1),
        "max_score": 5.0,
        "details": details,
    }