import math
import random
from typing import Any

DISTANCES = [
    [0.0,   24.26, 21.89, 30.94, 11.08],
    [24.26, 0.0,   8.50,  13.28, 17.79],
    [21.89, 8.50,  0.0,   9.26,  12.24],
    [30.94, 13.28, 9.26,  0.0,   20.57],
    [11.08, 17.79, 12.24, 20.57, 0.0]
]

def _to_float(val: Any) -> float | None:
    if val is None or isinstance(val, bool):
        return None
    s = str(val).strip().replace(",", ".")
    if not s:
        return None
    try:
        n = float(s)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None

def generate(seed: int | None = None) -> dict:
    return {
        "id": "new-methodology-v2",
        "title": "Новая методика: попарные расстояния между звёздами",
        "max_score": 10.0,
        "entry_point": "widget.html",
        "data": {
            "statement": (
                "Роскосмос и Росстат запустили новый аппарат для уточнения положений ярких звёзд. "
                "Измерения производятся по новой методике: определяются только попарные угловые расстояния "
                "между пятью яркими звёздами (ярче 3m), попавшими на один кадр. Восстановите взаимное "
                "расположение звёзд на доске, подберите минимальный диаметр круглого поля зрения, "
                "опознайте созвездие, оцените экваториальные координаты центра и порядок инструментальной погрешности."
            ),
            "distances": DISTANCES,
            "stars": ["1", "2", "3", "4", "5"],
            "anchors": {
                "1": {"x": 0.0, "y": 0.0},
                "4": {"x": 30.94, "y": 0.0}
            },
            "source": "Праководство, задача 1.2.3 (S.1.5); таблица S.8, с. 74; разбор, с. 73–76."
        },
        "schema": {
            "fields": [
                {"id": "diameter", "kind": "number", "label": "Минимальный диаметр поля зрения D", "unit": "°"},
                {
                    "id": "constellation",
                    "kind": "choice",
                    "label": "Созвездие",
                    "options": ["Лев", "Орион", "Орёл", "Лебедь", "Кассиопея", "Большая Медведица", "Пегас"]
                },
                {"id": "ra_hours", "kind": "number", "label": "Прямое восхождение центра α", "unit": "ч"},
                {"id": "dec_deg", "kind": "number", "label": "Склонение центра δ", "unit": "°"},
                {"id": "epsilon", "kind": "number", "label": "Оценка погрешности измерений ε", "unit": "°"}
            ]
        }
    }

def grade(seed: int, answers: dict) -> dict:
    answers = answers or {}
    details = {}
    total_score = 0.0

    # 1. Построение звёзд на доске по RMS невязок (макс. 3 балла)
    rms = None
    pos = answers.get("positions")
    if isinstance(pos, dict):
        pts = [pos.get(str(i)) or pos.get(i) for i in range(1, 6)]
        if all(isinstance(p, dict) and _to_float(p.get("x")) is not None and _to_float(p.get("y")) is not None for p in pts):
            coords = [(_to_float(p["x"]), _to_float(p["y"])) for p in pts]
            if all(max(abs(x), abs(y)) <= 10000 for x, y in coords):
                sq_sum = 0.0
                for i in range(5):
                    for j in range(i + 1, 5):
                        d_built = math.hypot(coords[i][0] - coords[j][0], coords[i][1] - coords[j][1])
                        sq_sum += (d_built - DISTANCES[i][j]) ** 2
                rms = round(math.sqrt(sq_sum / 10.0), 3)

    if rms is None:
        sc_pos = 0.0
    elif rms <= 0.8:
        sc_pos = 3.0
    elif rms <= 2.0:
        sc_pos = 2.0
    elif rms <= 3.5:
        sc_pos = 1.0
    else:
        sc_pos = 0.0

    total_score += sc_pos
    details["positions"] = {
        "user": rms,
        "truth": 0.13,
        "tol": 0.8,
        "score": sc_pos,
        "max": 3.0,
        "ok": sc_pos == 3.0,
        "message": "3 балла при RMS ≤ 0.8°, 2 балла при RMS ≤ 2.0°, 1 балл при RMS ≤ 3.5°."
    }

    # 2. Диаметр поля зрения D (макс. 2 балла)
    u_diam = _to_float(answers.get("diameter") or answers.get("min_fov"))
    ok_diam = u_diam is not None and abs(u_diam - 30.94) <= 1.2
    sc_diam = 2.0 if ok_diam else 0.0
    total_score += sc_diam
    details["diameter"] = {
        "user": u_diam,
        "truth": 30.94,
        "tol": 1.2,
        "score": sc_diam,
        "max": 2.0,
        "ok": ok_diam
    }

    # 3. Созвездие (макс. 1 балл)
    raw_c = answers.get("constellation")
    str_c = str(raw_c).strip().lower() if raw_c is not None else ""
    ok_c = str_c in ("лев", "leo")
    sc_c = 1.0 if ok_c else 0.0
    total_score += sc_c
    details["constellation"] = {
        "user": raw_c if raw_c else "—",
        "truth": "Лев",
        "tol": 0,
        "score": sc_c,
        "max": 1.0,
        "ok": ok_c
    }

    # 4. Прямое восхождение центра ra_hours (макс. 1 балл)
    u_ra = _to_float(answers.get("ra_hours") or answers.get("center_ra"))
    ok_ra = False
    if u_ra is not None and 0.0 <= u_ra <= 24.0:
        diff_ra = min(abs(u_ra - 11.0), 24.0 - abs(u_ra - 11.0))
        ok_ra = diff_ra <= 1.5
    sc_ra = 1.0 if ok_ra else 0.0
    total_score += sc_ra
    details["ra_hours"] = {
        "user": u_ra,
        "truth": 11.0,
        "tol": 1.5,
        "score": sc_ra,
        "max": 1.0,
        "ok": ok_ra
    }

    # 5. Склонение центра dec_deg (макс. 1 балл)
    u_dec = _to_float(answers.get("dec_deg") or answers.get("center_dec"))
    ok_dec = u_dec is not None and -90.0 <= u_dec <= 90.0 and abs(u_dec - 15.0) <= 6.0
    sc_dec = 1.0 if ok_dec else 0.0
    total_score += sc_dec
    details["dec_deg"] = {
        "user": u_dec,
        "truth": 15.0,
        "tol": 6.0,
        "score": sc_dec,
        "max": 1.0,
        "ok": ok_dec
    }

    # 6. Оценка погрешности epsilon (макс. 2 балла)
    # Принимается как авторская консервативная оценка через площади (1.0..4.0°),
    # так и оценка по невязке сферического/плоского треугольника (0.05..0.5°).
    u_eps = _to_float(answers.get("epsilon") or answers.get("inst_err"))
    ok_eps = u_eps is not None and ((1.0 <= u_eps <= 4.0) or (0.04 <= u_eps <= 0.5))
    sc_eps = 2.0 if ok_eps else 0.0
    total_score += sc_eps
    details["epsilon"] = {
        "user": u_eps,
        "truth": 2.0,
        "tol": 1.5,
        "score": sc_eps,
        "max": 2.0,
        "ok": ok_eps,
        "message": "В решении книги приведена консервативная оценка ~2° по невязкам площадей Герона (также засчитывается оценка 0.05–0.5° по невязкам дуг)."
    }

    return {
        "score": round(total_score, 1),
        "max_score": 10.0,
        "details": details,
        "solution": [
            "1. Минимальное круглое поле зрения определяется парой самых далёких звёзд 1 и 4: D ≈ 30.94° ≈ 31°.",
            "2. По характерной трапеции и «серпу» узнаётся созвездие Льва (1 — Регул α Leo, 2 — Альгиеба γ Leo, 3 — Зосма δ Leo, 4 — Денебола β Leo, 5 — Альгенуби ε Leo). Центр поля: α ≈ 11 ч, δ ≈ +15°.",
            "3. Авторская консервативная оценка погрешности по невязкам площадей треугольников (формула Герона) даёт ε ≈ 2° (при прямой подгонке на плоскости/сфере RMS невязок расстояний составляет ~0.1°)."
        ]
    }
