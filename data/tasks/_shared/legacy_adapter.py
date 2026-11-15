"""
Универсальный адаптер-мост (Legacy Task Adapter) для запуска задач из пакета `astrosim`
(старого проекта `astrosite_base`) на модульном ядре `astroprak` (v1.0.2 / v2.0) без переделки
исходного кода задач.

Поддерживает:
1. Все 11 генерируемых семейств `astrosim` (`rv-binary`, `cepheid-pl`, `transit-depth`,
   `comet-trails`, `jet-superluminal`, `descent-profile`, `galaxy-redshift`,
   `parallax-motion`, `rotation-mass`, `hubble-diagram`, `power-vertical`).
2. Любые архивные задачи ВсОШ (`2023-F-9-7`, `2026-R-11-10` и все остальные из 45 задач архива
   в формате `archive/<id>/task.json` + `solution.json` + `assets/`), как при наличии файла
   в `content/definitions/<id>.json`, так и напрямую из папки `archive/<id>/` без описания.
3. Полную олимпиадную проверку `astrosim.tasks.base.grade_fields` (допуск ±tol, половинный балл
   в ±2·tol, штраф −1 за избыточную точность значащих цифр, проверка погрешности ±σ в коридоре
   [σ/3, 3σ], поля yesno и choice), а также численные сверки `private.answer_checks` архивных задач.
4. Безопасное раскрытие пошагового авторского разбора (`solution_steps`, `solution_results`,
   изображений `assets/solution/*.webp`) только после сдачи работы (`POST /api/attempts/{id}/submit`).
"""
from __future__ import annotations

import base64
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

# Гарантируем, что директория `_shared` находится в sys.path
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# Подключаем numpy или чисто-питоновский полифилл np_compat (если в Docker-контейнере нет numpy)
from np_compat import ensure_numpy  # noqa: E402

ensure_numpy()

from astrosim.definitions import DIRECTORY as DEFS_DIR, load_definition  # noqa: E402
from astrosim.tasks.base import (  # noqa: E402
    GRADER_VERSION,
    FieldSpec,
    FieldVerdict,
    KeyEntry,
    Verdict,
    fmt,
    grade_fields as _base_grade_fields,
    parse_number,
)
from astrosim.tasks.registry import get_family  # noqa: E402

CONTENT_ROOT = DEFS_DIR.parent.resolve()


def _infer_archive_meta_from_id(task_id: str) -> dict[str, Any]:
    """Извлекает год, этап, класс и номер из ID вида '2023-F-9-7' или '2026-R-11-10'."""
    m = re.match(r"^(\d{4})-([FR])-(\d+)-(\d+)$", task_id)
    if not m:
        return {}
    year, st_code, grade, num = m.groups()
    return {
        "year": int(year),
        "stage": "final" if st_code == "F" else "regional",
        "grade": int(grade),
        "number": int(num),
        "points": 15,
    }


def load_or_synthesize_definition(task_id: str) -> dict[str, Any]:
    """
    Загружает `content/definitions/<task_id>.json`, а если для архивной задачи есть только папка
    `content/archive/<task_id>/task.json` (или локальный `archive/<task_id>/task.json`),
    автоматически синтезирует описание из `task.json`.
    """
    try:
        return load_definition(task_id)
    except Exception:
        pass

    candidates = [
        CONTENT_ROOT / "archive" / task_id / "task.json",
        _SHARED_DIR / "archive" / task_id / "task.json",
    ]
    for pkg_path in candidates:
        if pkg_path.is_file():
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
            pub = pkg.get("public", {})
            asks = []
            for p in pub.get("parts", []):
                for b in p.get("body", []):
                    if b.get("type") == "markdown" and b.get("text"):
                        asks.append(b["text"])
            return {
                "schema_version": "1.0",
                "id": task_id,
                "version": pkg.get("revision", 2),
                "kind": "archive",
                "title": pub.get("title", task_id),
                "language": pub.get("language", "ru"),
                "sources": pkg.get("sources", []),
                "statement_template": {
                    "title": pub.get("title", task_id),
                    "text": "",
                    "asks": asks or ["Решите задачу и запишите ответ."],
                    "note": "Условие, исходные данные и бланк доступны в задании. Решение раскрывается после сдачи.",
                },
                "answers": pub.get("answers", []),
                "parts": [
                    {"id": p.get("id", "original-task"), "answer_ids": p.get("answer_ids", [])}
                    for p in pub.get("parts", [])
                ],
                "tools": pub.get("tools", ["image-zoom", "image-ruler"]),
                "archive": _infer_archive_meta_from_id(task_id),
                "package_path": str(pkg_path.relative_to(CONTENT_ROOT))
                if pkg_path.is_relative_to(CONTENT_ROOT)
                else str(pkg_path),
            }

    raise ValueError(f"Описание или архивный пакет задачи не найдены: {task_id}")


def _resolve_package_path(pkg_rel: str) -> Path:
    p = Path(pkg_rel)
    if p.is_absolute() and p.is_file():
        return p
    cand = (CONTENT_ROOT / pkg_rel).resolve()
    if cand.is_file():
        return cand
    cand2 = (_SHARED_DIR / pkg_rel).resolve()
    if cand2.is_file():
        return cand2
    return cand


def _format_statement_html(statement: dict[str, Any]) -> str:
    """Формирует HTML-представление условия для обратной совместимости."""
    parts = []
    if statement.get("text"):
        parts.append(f"<p>{html.escape(str(statement['text']))}</p>")
    asks = statement.get("asks") or []
    if asks:
        items = "".join(f"<li>{html.escape(str(a))}</li>" for a in asks)
        parts.append(f"<ol class='legacy-asks'>{items}</ol>")
    if statement.get("note"):
        parts.append(f"<p class='legacy-note'>{html.escape(str(statement['note']))}</p>")
    return "\n".join(parts)


def _grade_fields_extended(
    raw_fields: list[dict[str, Any]],
    key_entries: list[KeyEntry],
    answers: dict[str, Any],
) -> Verdict:
    """
    Расширяет стандартный `astrosim.tasks.base.grade_fields` поддержкой полей `choice` и `text`,
    сохраняя 100% оригинальной логики ВсОШ для `number`, `number_with_error` и `yesno`.
    """
    by_id = {k.id: k for k in key_entries}
    results: list[FieldVerdict] = []

    for fdict in raw_fields:
        fid = fdict["id"]
        fkind = fdict.get("kind", "number")
        if fid not in by_id:
            continue
        k = by_id[fid]
        raw_val = answers.get(fid)
        raw_str = "" if raw_val is None else str(raw_val).strip()
        max_pts = k.points + k.points_error

        if fkind in ("number", "number_with_error", "yesno"):
            spec = FieldSpec(
                id=fid,
                label=fdict.get("label", fid),
                unit=fdict.get("unit", ""),
                kind=fkind,  # type: ignore[arg-type]
                hint=fdict.get("hint", ""),
            )
            sub_verdict = _base_grade_fields([spec], [k], {fid: raw_str})
            results.extend(sub_verdict.fields)
        elif fkind == "choice":
            if not raw_str:
                results.append(FieldVerdict(fid, 0, max_pts, "missing", "Вариант не выбран."))
            elif raw_str.lower() == str(k.value).strip().lower():
                results.append(FieldVerdict(fid, k.points, max_pts, "ok", "Верно."))
            else:
                results.append(
                    FieldVerdict(fid, 0, max_pts, "wrong", f"Правильный вариант: «{k.value}».")
                )
        else:
            if not raw_str:
                results.append(FieldVerdict(fid, 0, max_pts, "missing", "Поле пустое."))
            else:
                results.append(FieldVerdict(fid, k.points, max_pts, "ok", "Ответ принят."))

    total = sum(r.points for r in results)
    max_total = sum(r.max_points for r in results)
    return Verdict(GRADER_VERSION, total, max_total, results)


def _encode_asset_data_uri(file_path: Path, media_type: str) -> str:
    b64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{b64}"


def generate_legacy_task(task_id: str, seed: int | None = None) -> dict[str, Any]:
    """
    Генерирует вариант старой задачи `astrosim` (или загружает архивную задачу ВсОШ)
    и возвращает словарь в формате `astroprak` (`generate(seed)`).
    """
    actual_seed = int(seed) if seed is not None else 42
    defn = load_or_synthesize_definition(task_id)
    kind = defn.get("kind", "generated")

    # --- Ветка 1: Архивная / фиксированная задача ВсОШ ---
    if kind == "archive" or defn.get("package_path"):
        pkg_rel = defn.get("package_path")
        if pkg_rel:
            pkg_path = _resolve_package_path(pkg_rel)
            pkg_data = json.loads(pkg_path.read_text(encoding="utf-8"))
            pkg_dir = pkg_path.parent
        else:
            pkg_data = None
            pkg_dir = CONTENT_ROOT

        public_assets = []
        if pkg_data:
            for asset in pkg_data.get("assets", []):
                if asset.get("access") == "public":
                    apath = pkg_dir / asset["path"]
                    data_uri = _encode_asset_data_uri(apath, asset["media_type"]) if apath.is_file() else ""
                    public_assets.append({
                        "id": asset["id"],
                        "media_type": asset["media_type"],
                        "url": data_uri,
                    })
            pub_block = pkg_data["public"]
            statement_blocks = pub_block.get("statement", [])
            parts = pub_block.get("parts", [])
            answers = pub_block.get("answers", defn.get("answers", []))
            tools = pub_block.get("tools", defn.get("tools", []))
            sources = pkg_data.get("sources", defn.get("sources", []))
            title = pub_block.get("title", defn.get("title", task_id))
        else:
            st_tmpl = defn.get("statement_template", {})
            statement_blocks = [{"type": "markdown", "text": st_tmpl.get("text", "")}]
            parts = [
                {
                    "id": p["id"],
                    "answer_ids": p.get("answer_ids", []),
                    "body": [{"type": "markdown", "text": ask_txt}],
                }
                for p, ask_txt in zip(defn.get("parts", []), st_tmpl.get("asks", []))
            ]
            answers = defn.get("answers", [])
            tools = defn.get("tools", [])
            sources = defn.get("sources", [])
            title = defn.get("title", task_id)

        archive_meta = defn.get("archive") or _infer_archive_meta_from_id(task_id)
        max_pts = float(archive_meta.get("points", 15.0))

        return {
            "id": task_id,
            "title": title,
            "kind": "archive",
            "max_score": max_pts,
            "entry_point": "widget.html",
            "data": {
                "mode": "legacy_archive",
                "task_id": task_id,
                "seed": 0,
                "title": title,
                "archive": archive_meta,
                "statement_blocks": statement_blocks,
                "parts": parts,
                "fields": answers,
                "tools": tools,
                "sources": sources,
                "assets": public_assets,
                "statement": defn.get("statement_template", {}).get("text", title),
            },
            "schema": {
                "fields": [f for f in answers if f.get("kind") != "points"]
            },
        }

    # --- Ветка 2: Генерируемая задача astrosim ---
    model_id = defn.get("model", {}).get("id", task_id)
    module = get_family(model_id)
    pkg = module.generate(actual_seed)
    pub = pkg.public
    priv = pkg.private

    defn_answers_by_id = {a["id"]: a for a in defn.get("answers", [])}
    fields = []
    for f in pub.get("fields", []):
        merged = dict(f)
        if f["id"] in defn_answers_by_id and "options" in defn_answers_by_id[f["id"]]:
            merged["options"] = defn_answers_by_id[f["id"]]["options"]
        fields.append(merged)

    key_list = priv.get("key", [])
    max_score = sum(k.get("points", 0) + k.get("points_error", 0) for k in key_list) or 10.0

    statement_obj = pub.get("statement", {})
    plot_data = pub.get("data", {})

    series = plot_data.get("series", [])
    axes = plot_data.get("axes")
    plot_meta = pub.get("plot")
    if not axes and "z_points" in plot_data:
        z_pts = plot_data["z_points"]
        z_min = float(plot_data.get("z_min", -1.0))
        z_max = float(plot_data.get("z_max", 1.0))
        m_bins = 10
        w = (z_max - z_min) / m_bins
        counts = [0] * m_bins
        for z in z_pts:
            b = int((z - z_min) // w)
            b = max(0, min(m_bins - 1, b))
            counts[b] += 1
        dens_pts = [[round(z_min + (i + 0.5) * w, 3), round(counts[i] / w, 1)] for i in range(m_bins)]
        max_d = max((p[1] for p in dens_pts), default=100.0)
        tick_y = 50.0 if max_d <= 300 else 100.0
        y_hi = float((int(max_d // tick_y) + 1) * tick_y)
        series = [{"id": "n_z", "label": "плотность n(z)", "marker": "dot", "points": dens_pts}]
        axes = {
            "x": {"label": "высота z, кпк", "min": z_min, "max": z_max, "tick": 0.2},
            "y": {"label": "плотность n(z), кпк⁻¹", "min": 0.0, "max": y_hi, "tick": tick_y},
        }
        plot_meta = {
            "caption": "Распределение плотности объектов по высоте z (разбиение M = 10)",
            "x": {"key": "z", "unit": "кпк", "decimals": 2},
            "y": {"key": "n", "unit": "кпк⁻¹", "decimals": 1, "sign": False},
        }

    st_title = statement_obj.get("title") or defn.get("title", task_id)
    full_title = f"{defn.get('title', task_id)} — {st_title}" if st_title != defn.get("title") else st_title

    return {
        "id": task_id,
        "title": full_title,
        "kind": "generated",
        "generator_version": pkg.generator_version,
        "seed": actual_seed,
        "max_score": float(max_score),
        "entry_point": "widget.html",
        "data": {
            "mode": "legacy_generated",
            "task_id": task_id,
            "seed": actual_seed,
            "generator_version": pkg.generator_version,
            "family_label": pub.get("family_label", defn.get("title", task_id)),
            "statement_obj": statement_obj,
            "statement": _format_statement_html(statement_obj),
            "series": series,
            "segments": plot_data.get("segments", []),
            "axes": axes,
            "spherical": bool(plot_data.get("spherical", False)),
            "raw_data": plot_data,
            "plot": plot_meta,
            "tools": pub.get("tools", defn.get("tools", ["cursor", "loupe", "extremum", "segment"])),
            "fields": fields,
            "parts": defn.get("parts", []),
            "given": pub.get("given", {}),
            "sources": defn.get("sources", []),
        },
        "schema": {
            "fields": fields,
        },
    }


def grade_legacy_task(task_id: str, seed: int | None, answers: dict[str, Any] | None) -> dict[str, Any]:
    """
    Проверяет решение ученика по правилам `astrosim` и возвращает результат
    в формате `astroprak` (с полным протоколом `details`, `verdict` и пошаговым `solution_steps`).
    """
    actual_seed = int(seed) if seed is not None else 42
    safe_answers = answers or {}
    defn = load_or_synthesize_definition(task_id)
    kind = defn.get("kind", "generated")

    # --- Ветка 1: Архивная задача ---
    if kind == "archive" or defn.get("package_path"):
        pkg_rel = defn.get("package_path")
        sol_steps = []
        sol_assets = []
        sol_results = []
        checks_out = []
        checks_by_id = {}
        answers_list = defn.get("answers", [])

        if pkg_rel:
            pkg_path = _resolve_package_path(pkg_rel)
            pkg_dir = pkg_path.parent
            pkg_data = json.loads(pkg_path.read_text(encoding="utf-8"))
            answers_list = pkg_data.get("public", {}).get("answers", answers_list)
            sol_path = pkg_path.with_name("solution.json")
            sol_data = json.loads(sol_path.read_text(encoding="utf-8")) if sol_path.is_file() else {}

            for asset in [*pkg_data.get("assets", []), *sol_data.get("assets", [])]:
                if asset.get("access") in ("public", "solution"):
                    apath = pkg_dir / asset["path"]
                    data_uri = _encode_asset_data_uri(apath, asset["media_type"]) if apath.is_file() else ""
                    sol_assets.append({
                        "id": asset["id"],
                        "media_type": asset["media_type"],
                        "url": data_uri,
                    })

            for method in sol_data.get("methods", []):
                for st in method.get("steps", []):
                    sol_steps.append({
                        "id": st.get("id", "step"),
                        "title": st.get("title", "Решение"),
                        "blocks": st.get("body", []),
                    })
                for res_item in method.get("results", []):
                    txt_blocks = [b.get("text", "") for b in res_item.get("body", []) if b.get("type") == "markdown"]
                    if txt_blocks:
                        sol_results.append({
                            "answer_id": res_item.get("answer_id", ""),
                            "text": " ".join(txt_blocks),
                        })

            for chk in pkg_data.get("private", {}).get("answer_checks", []):
                aid = chk["answer_id"]
                raw = str(safe_answers.get(aid, "")).strip()
                val = parse_number(raw)
                status = (
                    "missing"
                    if not raw
                    else "unparsed"
                    if val is None
                    else ("ok" if abs(val - chk["value"]) <= chk["tolerance"] + 1e-12 else "wrong")
                )
                chk_entry = {
                    "answer_id": aid,
                    "value": chk["value"],
                    "tolerance": chk["tolerance"],
                    "status": status,
                    "comment": {
                        "missing": "Ответ не указан.",
                        "unparsed": "Не удалось прочитать число.",
                        "ok": "Число согласуется с эталоном. Обоснование сверьте с разбором.",
                        "wrong": "Число выходит за установленный допуск.",
                    }[status],
                    "rationale": chk.get("rationale", ""),
                }
                checks_out.append(chk_entry)
                checks_by_id[aid] = chk_entry

        archive_meta = defn.get("archive") or _infer_archive_meta_from_id(task_id)
        max_pts = float(archive_meta.get("points", 15.0))
        details = {}
        for f in answers_list:
            if f.get("kind") == "points":
                continue
            fid = f["id"]
            uval = str(safe_answers.get(fid, "")).strip()
            if fid in checks_by_id:
                c = checks_by_id[fid]
                details[fid] = {
                    "user": uval if uval else None,
                    "truth": fmt(float(c["value"]), 3),
                    "tol": fmt(float(c["tolerance"]), 2),
                    "score": 0.0,
                    "max": 0.0,
                    "ok": c["status"] == "ok",
                    "status": c["status"],
                    "comment": f"{c['comment']} ({c['rationale']})" if c.get("rationale") else c["comment"],
                    "penalties": [],
                    "label": f.get("label", fid),
                    "unit": f.get("unit", ""),
                }
            else:
                details[fid] = {
                    "user": uval if uval else None,
                    "truth": "см. официальный разбор",
                    "tol": "—",
                    "score": 0.0,
                    "max": 0.0,
                    "ok": bool(uval),
                    "status": "ok" if uval else "missing",
                    "comment": "Ответ сохранён. Сверьте решение с официальными критериями.",
                    "penalties": [],
                    "label": f.get("label", fid),
                    "unit": f.get("unit", ""),
                }

        return {
            "score": 0.0,
            "max_score": max_pts,
            "mode": "manual",
            "details": details,
            "answer_checks": checks_out,
            "solution_title": "Официальное решение и критерии",
            "solution_steps": sol_steps,
            "solution_results": sol_results,
            "solution_assets": sol_assets,
            "sources": defn.get("sources", []),
        }

    # --- Ветка 2: Генерируемая задача astrosim ---
    model_id = defn.get("model", {}).get("id", task_id)
    module = get_family(model_id)
    pkg = module.generate(actual_seed)
    pub = pkg.public
    priv = pkg.private

    defn_answers = defn.get("answers", pub.get("fields", []))
    key_entries = [KeyEntry(**k) for k in priv.get("key", [])]
    key_by_id = {k.id: k for k in key_entries}
    field_by_id = {f["id"]: f for f in defn_answers}

    verdict = _grade_fields_extended(defn_answers, key_entries, safe_answers)

    details: dict[str, Any] = {}
    for fv in verdict.fields:
        k = key_by_id[fv.id]
        fspec = field_by_id.get(fv.id, {"id": fv.id, "label": fv.id, "unit": "", "kind": "number"})
        raw_user = safe_answers.get(fv.id)
        raw_str = "" if raw_user is None else str(raw_user).strip()

        if isinstance(k.value, (int, float)):
            truth_fmt = fmt(float(k.value), k.sigfig_allowed)
            if fspec.get("kind") == "number_with_error" and k.sigma is not None:
                truth_fmt = f"{truth_fmt} ± {fmt(float(k.sigma), 1)}"
        else:
            truth_fmt = str(k.value)

        tol_fmt = fmt(float(k.tolerance), 2) if k.tolerance is not None else "—"

        details[fv.id] = {
            "user": raw_str if raw_str != "" else None,
            "truth": truth_fmt,
            "truth_raw": k.value,
            "tol": tol_fmt,
            "tol_raw": k.tolerance,
            "score": float(fv.points),
            "max": float(fv.max_points),
            "ok": fv.status == "ok",
            "status": fv.status,
            "comment": fv.comment,
            "penalties": fv.penalties,
            "label": fspec.get("label", fv.id),
            "unit": fspec.get("unit", ""),
        }

    sol_texts = priv.get("solution", [])
    sol_tmpl_steps = defn.get("solution_template", {}).get("steps", [])
    solution_steps = []
    for idx, step_spec in enumerate(sol_tmpl_steps):
        text_val = sol_texts[idx] if idx < len(sol_texts) else step_spec.get("text", "")
        solution_steps.append({
            "id": step_spec.get("id", f"step-{idx + 1}"),
            "title": step_spec.get("title", f"Шаг {idx + 1}"),
            "text": text_val,
            "answer_ids": step_spec.get("answer_ids", []),
            "part_ids": step_spec.get("part_ids", []),
        })

    solution_results = []
    for k in key_entries:
        fspec = field_by_id.get(k.id, {"id": k.id, "label": k.id, "unit": "", "kind": "number"})
        val_str = fmt(float(k.value), k.sigfig_allowed) if isinstance(k.value, (int, float)) else str(k.value)
        if fspec.get("kind") == "number_with_error" and k.sigma is not None:
            val_str += f" ± {fmt(float(k.sigma), 1)}"
        unit_str = fspec.get("unit", "")
        solution_results.append({
            "answer_id": k.id,
            "label": fspec.get("label", k.id),
            "value": val_str,
            "unit": unit_str,
            "text": f"{fspec.get('label', k.id)} = {val_str} {unit_str}".strip(),
        })

    return {
        "score": float(verdict.total),
        "max_score": float(verdict.max_total),
        "grader_version": verdict.grader_version,
        "details": details,
        "verdict": verdict.to_dict(),
        "solution_title": defn.get("solution_template", {}).get("title", "Разбор задачи"),
        "solution_steps": solution_steps,
        "solution_results": solution_results,
    }

def sync_all_legacy_tasks(overwrite: bool = False) -> int:
    """
    При прямом запуске `python3 data/tasks/_shared/legacy_adapter.py` сканирует
    папки `astrosim/content/archive/` и `astrosim/content/definitions/` и автоматически
    создаёт обёртки `data/tasks/<task_id>/` (manifest.json, generator.py, widget.html).
    """
    tasks_root = _SHARED_DIR.parent
    discovered_ids: list[str] = []

    # 1. Ищем все задачи в definitions/
    if DEFS_DIR.is_dir():
        for f in sorted(DEFS_DIR.glob("*.json")):
            discovered_ids.append(f.stem)

    # 2. Ищем все архивные задачи в archive/
    for arch_root in (CONTENT_ROOT / "archive", _SHARED_DIR / "archive"):
        if arch_root.is_dir():
            for d in sorted(arch_root.iterdir()):
                if d.is_dir() and (d / "task.json").is_file() and d.name not in discovered_ids:
                    discovered_ids.append(d.name)

    created_count = 0
    for task_id in discovered_ids:
        out_dir = tasks_root / task_id
        # Не перезаписываем уже существующие кастомные задачи (например, power-vertical), если не задан флаг
        if out_dir.exists() and (out_dir / "manifest.json").is_file() and not overwrite:
            continue

        try:
            defn = load_or_synthesize_definition(task_id)
        except Exception as e:
            print(f"[SKIP] {task_id}: {e}")
            continue

        kind = defn.get("kind", "generated")
        raw_title = defn.get("title", task_id)
        arch = defn.get("archive") or _infer_archive_meta_from_id(task_id)

        if kind == "archive" and arch.get("year") and arch.get("grade"):
            full_title = (
                f"ВсОШ {arch['year']} ({arch['grade']} кл.): {raw_title}"
                if not raw_title.startswith("ВсОШ")
                else raw_title
            )
            classes = [int(arch["grade"])]
            max_score = float(arch.get("points", 15.0))
            topic = "практический тур ВсОШ"
        else:
            full_title = raw_title
            classes = [9, 10, 11]
            max_score = 25.0
            topic = "астрофизика и анализ данных"

        out_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "schema_version": "2.0",
            "id": task_id,
            "title": full_title,
            "kind": kind,
            "version": "2.0.0",
            "hidden": False,
            "tags": {
                "class": classes,
                "topic": topic,
                "skills": ["практический тур", "анализ данных"],
            },
            "max_score": max_score,
            "entry_point": "widget.html",
            "generator_script": "generator.py",
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        gen_code = (
            f'"""\nАвтоматически сгенерированная точка входа генератора задачи `{task_id}`.\n"""\n'
            "from __future__ import annotations\n\n"
            "import sys\n"
            "from pathlib import Path\n\n"
            f"TASK_ID = {task_id!r}\n\n"
            '_SHARED_DIR = Path(__file__).resolve().parent.parent / "_shared"\n'
            "if str(_SHARED_DIR) not in sys.path:\n"
            "    sys.path.insert(0, str(_SHARED_DIR))\n\n"
            "from legacy_adapter import generate_legacy_task, grade_legacy_task  # noqa: E402\n\n\n"
            "def generate(seed: int | None = None) -> dict:\n"
            "    return generate_legacy_task(TASK_ID, seed)\n\n\n"
            "def grade(seed: int, answers: dict) -> dict:\n"
            "    return grade_legacy_task(TASK_ID, seed, answers)\n"
        )
        (out_dir / "generator.py").write_text(gen_code, encoding="utf-8")

        widget_code = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(full_title)}</title>
  <link rel="stylesheet" href="/static/tasks/_shared/astroplot.css">
  <link rel="stylesheet" href="/static/tasks/_shared/legacy_widget.css">
  <script src="/static/tasks/_shared/astroplot.js"></script>
  <script src="/static/tasks/_shared/legacy_widget.js"></script>
</head>
<body>
  <div id="widget-root" data-task-id="{html.escape(task_id)}"></div>
  <script>
    document.addEventListener('DOMContentLoaded', function () {{
      LegacyTaskWidget.mount('#widget-root');
    }});
  </script>
</body>
</html>
"""
        (out_dir / "widget.html").write_text(widget_code, encoding="utf-8")
        created_count += 1
        print(f"[OK] Создана задача: data/tasks/{task_id} ({full_title})")

    print(f"Готово! Найдено задач в astrosim: {len(discovered_ids)}, создано новых папок: {created_count}")
    return created_count


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Генерация папок задач из astrosim в data/tasks/")
    parser.add_argument("--overwrite", action="store_true", help="Перезаписать существующие обёртки")
    args = parser.parse_args()
    sync_all_legacy_tasks(overwrite=args.overwrite)
