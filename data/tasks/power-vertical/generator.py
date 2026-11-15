import math
import random
from typing import Any

def _compute_truth(seed: int | None = None) -> dict[str, Any]:
    """Восстанавливает истинные параметры и выборку по зерну."""
    rng = random.Random(seed)
    
    h_true = round(rng.uniform(0.18, 0.28), 2)
    n_total = 100
    noise_frac = 0.15
    n_disk = int(n_total * (1.0 - noise_frac))
    
    n0_true = round(n_disk / (2.0 * h_true * (1.0 - math.exp(-1.0 / h_true))), 1)

    observations = []
    for _ in range(n_disk):
        u = rng.random()
        sign = 1.0 if rng.random() > 0.5 else -1.0
        z = sign * (-h_true * math.log(1.0 - u * (1.0 - math.exp(-1.0 / h_true))))
        observations.append(round(z, 3))
    
    for _ in range(n_total - n_disk):
        observations.append(round(rng.uniform(-1.0, 1.0), 3))
        
    rng.shuffle(observations)

    return {
        "h_true": h_true,
        "n0_true": n0_true,
        "observations": observations,
        "z_min": -1.0,
        "z_max": 1.0
    }

def generate(seed: int | None = None) -> dict:
    actual_seed = seed if seed is not None else 42
    truth = _compute_truth(actual_seed)

    statement_text = (
        "Вам даны значения z-координат («высот» над диском в кпк) модельных объектов плоской подсистемы "
        "Галактики (N = 100). Проведите исследование пространственного распределения: выберите количество "
        "интервалов разбиения, подсчитайте населённость групп, определите форму теоретического профиля "
        "и оцените его физические параметры."
    )

    return {
        "id": "power-vertical",
        "title": "Power Vertical: Статистика вертикального диска",
        "max_score": 5.0,
        "entry_point": "widget.html",
        "data": {
            "statement": statement_text,
            "observations": truth["observations"],
            "h_model": truth["h_true"],
            "n0_model": truth["n0_true"],
            "z_min": truth["z_min"],
            "z_max": truth["z_max"]
        },
        "schema": {
            "fields": [
                {
                    "id": "initial_m",
                    "kind": "number",
                    "label": "Выбранное число групп M",
                    "unit": "шт"
                },
                {
                    "id": "model_type",
                    "kind": "choice",
                    "label": "Модель профиля",
                    "options": [
                        "Гауссово: n(z) = n0 * exp(-z^2 / (2 h^2))",
                        "Дельта-всплеск: n(z) = n0 * delta(z)",
                        "Равномерное: n(z) = n0 при |z| <= h",
                        "Экспоненциальное: n(z) = n0 * exp(-|z| / h)",
                        "Степенное: n(z) = n0 / (1 + |z| / h)^2"
                    ]
                },
                {"id": "h_val", "kind": "number", "label": "Шкала высот h", "unit": "кпк"},
                {"id": "n0_val", "kind": "number", "label": "Концентрация n0", "unit": "кпк⁻¹"}
            ]
        }
    }

def grade(seed: int, answers: dict) -> dict:
    try:
        truth = _compute_truth(seed)
    except Exception:
        return {"score": 0.0, "max_score": 5.0, "details": {}}

    answers = answers or {}
    total_score = 0.0
    details = {}

    # 1. Выбор количества интервалов M (1 балл: M in [9, 11])
    raw_m = answers.get("initial_m")
    m_ok = False
    user_m = None
    try:
        user_m = int(raw_m)
        if 9 <= user_m <= 11:
            m_ok = True
    except (ValueError, TypeError):
        pass

    score_m = 1.0 if m_ok else 0.0
    total_score += score_m
    details["initial_m"] = {
        "user": user_m,
        "truth": 10,
        "tol": 1,
        "score": score_m,
        "max": 1.0,
        "ok": m_ok
    }

    # 2. Подсчет точек по столбцам (1 балл: расхождение во всех бинах <= 3)
    user_counts = answers.get("user_counts")
    counts_ok = False
    max_count_diff = None

    if user_m and isinstance(user_counts, list) and len(user_counts) == user_m:
        w = (truth["z_max"] - truth["z_min"]) / user_m
        true_counts = [0] * user_m
        for z in truth["observations"]:
            b = math.floor((z - truth["z_min"]) / w)
            if b < 0:
                b = 0
            if b >= user_m:
                b = user_m - 1
            true_counts[b] += 1

        diffs = []
        for i in range(user_m):
            try:
                u_cnt = int(user_counts[i])
            except (ValueError, TypeError):
                u_cnt = 0
            diffs.append(abs(u_cnt - true_counts[i]))

        max_count_diff = max(diffs) if diffs else None
        if max_count_diff is not None and max_count_diff < 4:
            counts_ok = True

    score_counts = 1.0 if counts_ok else 0.0
    total_score += score_counts
    details["bin_counts"] = {
        "user": f"макс. расхождение {max_count_diff} шт" if max_count_diff is not None else "нет данных",
        "truth": "во всех группах",
        "tol": 3,
        "score": score_counts,
        "max": 1.0,
        "ok": counts_ok
    }

    # 3. Тип распределения (1 балл: Экспоненциальное)
    model_type = str(answers.get("model_type", "")).strip().lower()
    model_ok = ("экспоненциальное" in model_type) or (model_type == "exp")
    score_model = 1.0 if model_ok else 0.0
    total_score += score_model
    details["model_type"] = {
        "user": answers.get("model_type"),
        "truth": "Экспоненциальное",
        "tol": 0,
        "score": score_model,
        "max": 1.0,
        "ok": model_ok
    }

    # 4. Масштабная высота h (1 балл, погрешность 7%)
    raw_h = answers.get("h_val")
    h_ok = False
    user_h = None
    h_true = truth["h_true"]
    h_tol = round(h_true * 0.4, 3)
    try:
        user_h = float(str(raw_h).replace(",", ".").strip())
        diff_h = abs(user_h - h_true)
        if diff_h <= h_tol + 1e-6:
            h_ok = True
    except (ValueError, TypeError):
        pass

    score_h = 1.0 if h_ok else 0.0
    total_score += score_h
    details["h_val"] = {
        "user": user_h,
        "truth": h_true,
        "tol": h_tol,
        "score": score_h,
        "max": 1.0,
        "ok": h_ok
    }

    # 5. Концентрация n0 (1 балл, погрешность 7%)
    raw_n0 = answers.get("n0_val")
    n0_ok = False
    user_n0 = None
    n0_true = truth["n0_true"]
    n0_tol = round(n0_true * 0.2, 1)
    try:
        user_n0 = float(str(raw_n0).replace(",", ".").strip())
        diff_n0 = abs(user_n0 - n0_true)
        if diff_n0 <= n0_tol + 1e-6:
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
        "ok": n0_ok
    }

    return {
        "score": round(total_score, 1),
        "max_score": 5.0,
        "details": details
    }