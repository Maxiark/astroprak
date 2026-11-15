import math
import random
from typing import Any

BASE_STARS = [
    {"id": "alpha",  "name": "α (Альтаир)", "ra_h": 19, "ra_m": 50.8, "dec_d": 8,  "dec_m": 52, "mu": 660, "gamma": 53.7},
    {"id": "beta",   "name": "β (Альшаин)", "ra_h": 19, "ra_m": 55.3, "dec_d": 6,  "dec_m": 24, "mu": 485, "gamma": 175.4},
    {"id": "delta",  "name": "δ Орла",      "ra_h": 19, "ra_m": 25.5, "dec_d": 3,  "dec_m": 7,  "mu": 268, "gamma": 72.1},
    {"id": "zeta",   "name": "ζ Орла",      "ra_h": 19, "ra_m": 5.4,  "dec_d": 13, "dec_m": 52, "mu": 88,  "gamma": 183.0},
    {"id": "theta",  "name": "θ Орла",      "ra_h": 20, "ra_m": 11.3, "dec_d": 0,  "dec_m": -49,"mu": 40,  "gamma": 81.4},
    {"id": "lambda", "name": "λ Орла",      "ra_h": 19, "ra_m": 6.2,  "dec_d": -4, "dec_m": -53,"mu": 91,  "gamma": 191.9}
]

def _compute_truth(seed: int | None = None) -> dict[str, Any]:
    rng = random.Random(seed if seed is not None else 42)
    t_years = 40000
    
    stars = []
    for s in BASE_STARS:
        ra_deg = (s["ra_h"] + s["ra_m"] / 60.0) * 15.0
        if s["dec_d"] < 0 or s["dec_m"] < 0:
            dec_deg = -(abs(s["dec_d"]) + abs(s["dec_m"]) / 60.0)
        else:
            dec_deg = s["dec_d"] + s["dec_m"] / 60.0
            
        mu_arcsec = s["mu"] * 1e-3
        rad = math.radians(s["gamma"])
        
        # Смещение за 40000 лет (в угловых минутах и градусах)
        # Позиционный угол отсчитывается от Севера к Востоку (против часовой стрелки)
        # За 40000 лет в прошлое (-t):
        d_dec_arcmin = -(mu_arcsec * math.cos(rad) * t_years) / 60.0
        d_ra_proj_arcmin = -(mu_arcsec * math.sin(rad) * t_years) / 60.0
        
        past_dec_deg = dec_deg + d_dec_arcmin / 60.0
        past_ra_deg = ra_deg + (d_ra_proj_arcmin / 60.0) / math.cos(math.radians(dec_deg))
        
        stars.append({
            "id": s["id"],
            "name": s["name"],
            "ra_h": s["ra_h"],
            "ra_m": s["ra_m"],
            "dec_str": f"{'+' if dec_deg >= 0 else '-'}{abs(s['dec_d']):02d}° {abs(s['dec_m']):02d}'",
            "ra_deg": round(ra_deg, 4),
            "dec_deg": round(dec_deg, 4),
            "mu": s["mu"],
            "gamma": s["gamma"],
            "d_ra_arcmin": round(d_ra_proj_arcmin, 1),
            "d_dec_arcmin": round(d_dec_arcmin, 1),
            "past_ra_deg": round(past_ra_deg, 4),
            "past_dec_deg": round(past_dec_deg, 4)
        })
        
    a = stars[0]
    b = stars[1]
    dra = math.radians(a["past_ra_deg"] - b["past_ra_deg"])
    d1 = math.radians(a["past_dec_deg"])
    d2 = math.radians(b["past_dec_deg"])
    cos_t = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(dra)
    dist_ab = round(math.degrees(math.acos(max(-1.0, min(1.0, cos_t)))), 1)
    
    return {
        "t_years": t_years,
        "stars": stars,
        "alpha_dra_true": a["d_ra_arcmin"],
        "alpha_ddec_true": a["d_dec_arcmin"],
        "beta_dra_true": b["d_ra_arcmin"],
        "beta_ddec_true": b["d_dec_arcmin"],
        "dist_ab_true": dist_ab
    }

def generate(seed: int | None = None) -> dict:
    actual_seed = seed if seed is not None else 42
    truth = _compute_truth(actual_seed)

    statement_text = (
        "В таблице приведены координаты и собственные движения ярких звёзд созвездия Орла на текущий момент. "
        "Задано полное собственное движение и позиционный угол его направления, отсчитываемый от направления на "
        "Северный полюс мира против часовой стрелки. Постройте положение этих звёзд в настоящий момент и 40 000 лет назад, "
        "как могли бы их видеть последние неандертальцы. Найдите угловое расстояние между звёздами α и β Орла 40 000 лет назад."
    )

    return {
        "id": "aquila-40k-v2",
        "title": "Орёл 40-тысячелетия: собственные движения звёзд",
        "max_score": 5.0,
        "entry_point": "widget.html",
        "data": {
            "statement": statement_text,
            "t_years": truth["t_years"],
            "stars": truth["stars"]
        },
        "schema": {
            "fields": [
                {"id": "alpha_dra", "kind": "number", "label": "Смещение α Орла по Δα·cos δ (-40 тыс. лет)", "unit": "угл. мин (')"},
                {"id": "alpha_ddec", "kind": "number", "label": "Смещение α Орла по Δδ (-40 тыс. лет)", "unit": "угл. мин (')"},
                {"id": "beta_ddec", "kind": "number", "label": "Смещение β Орла по Δδ (-40 тыс. лет)", "unit": "угл. мин (')"},
                {"id": "dist_ab", "kind": "number", "label": "Угловое расстояние между α и β Орла 40 000 лет назад", "unit": "°"}
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

    # 1. Смещение Альтаира по прямому восхождению в угл. минутах (1 балл)
    checks = [
        ("alpha_dra", truth["alpha_dra_true"], 2.0, 1.0),
        ("alpha_ddec", truth["alpha_ddec_true"], 2.0, 1.0),
        ("beta_ddec", truth["beta_ddec_true"], 2.0, 1.0),
        ("dist_ab", truth["dist_ab_true"], 0.15, 2.0)
    ]

    for fid, t_val, tol, weight in checks:
        raw = answers.get(fid)
        ok = False
        u_val = None
        try:
            u_val = float(str(raw).replace(",", ".").strip())
            if abs(u_val - t_val) <= tol:
                ok = True
        except (ValueError, TypeError):
            pass

        sc = weight if ok else 0.0
        total_score += sc
        details[fid] = {
            "user": u_val,
            "truth": t_val,
            "tol": tol,
            "score": sc,
            "max": weight,
            "ok": ok
        }

    return {
        "score": round(total_score, 1),
        "max_score": 5.0,
        "details": details
    }
