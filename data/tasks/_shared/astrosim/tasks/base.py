"""Общая форма задания и общие правила проверки.

TaskPackage делится на public (то, что уходит участнику: условие, данные, поля бланка) и private
(истина, ключ с допусками, эталонное решение). Клиент никогда не получает private.

Правила проверки повторяют культуру критериев ВсОШ (docs/research/format.md §3): целые баллы;
допуск задан явно; ответ внутри допуска — полный балл, внутри двойного допуска — половина (вниз);
избыточная точность — минус балл; погрешность принимается, если она в пределах [σ/3, 3σ] от эталонной.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

FieldKind = Literal["number", "number_with_error", "yesno"]


@dataclass(frozen=True)
class FieldSpec:
    id: str
    label: str            # подпись на бланке (может содержать индексы в виде K_A — клиент форматирует)
    unit: str             # единица, как она напечатана на бланке; пусто для да/нет
    kind: FieldKind
    hint: str = ""


@dataclass(frozen=True)
class KeyEntry:
    id: str
    value: float | str
    points: int
    tolerance: float | None = None      # абсолютный допуск для number / части «значение»
    sigma: float | None = None          # эталонная погрешность для number_with_error
    points_error: int = 0               # баллы за часть «± погрешность»
    sigfig_allowed: int = 2             # больше — «избыточная точность», −1


@dataclass
class TaskPackage:
    family: str
    generator_version: str
    seed: int
    public: dict[str, Any]
    private: dict[str, Any]

    def to_dict(self, include_private: bool = False) -> dict[str, Any]:
        out = {"family": self.family, "generator_version": self.generator_version, "seed": self.seed, "public": self.public}
        if include_private:
            out["private"] = self.private
        return out


@dataclass
class FieldVerdict:
    id: str
    points: int
    max_points: int
    status: str            # ok | near | wrong | missing | unparsed
    comment: str
    penalties: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    grader_version: str
    total: int
    max_total: int
    fields: list[FieldVerdict]

    def to_dict(self) -> dict[str, Any]:
        return {"grader_version": self.grader_version, "total": self.total, "max_total": self.max_total,
                "fields": [asdict(f) for f in self.fields]}


GRADER_VERSION = "0.1.0"

_NUM = r"[-+−]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?"


def parse_number(text: str) -> float | None:
    """«0,74», «+56,2», «5.1e2», «−3» → число; иначе None."""
    m = re.fullmatch(r"\s*(" + _NUM + r")\s*", text or "")
    if not m:
        return None
    return float(m.group(1).replace(",", ".").replace("−", "-"))


def parse_number_with_error(text: str) -> tuple[float | None, float | None]:
    """«0,056 ± 0,002», «0.056+-0.002», «0,056» → (значение, погрешность | None)."""
    t = (text or "").strip()
    m = re.fullmatch(r"\s*(" + _NUM + r")\s*(?:±|\+-|\+/-|\+\/−)\s*(" + _NUM + r")\s*", t)
    if m:
        return parse_number(m.group(1)), parse_number(m.group(2))
    return parse_number(t), None


def parse_yesno(text: str) -> bool | None:
    t = (text or "").strip().lower().rstrip(".!")
    if t in {"да", "yes", "д", "y", "разрешима", "можно"}:
        return True
    if t in {"нет", "no", "н", "n", "не разрешима", "неразрешима", "нельзя"}:
        return False
    return None


def significant_figures(text: str) -> int:
    """Число значащих цифр в записи числа. Хвостовые нули целого без запятой значащими не считаются."""
    t = (text or "").strip().replace("−", "-").replace(",", ".")
    m = re.fullmatch(r"[-+]?(\d*)(?:\.(\d*))?(?:[eE][-+]?\d+)?", t)
    if not m:
        return 0
    int_part, frac_part = m.group(1) or "", m.group(2)
    if frac_part is None:
        digits = int_part.lstrip("0").rstrip("0")
        return len(digits) if digits else 1
    digits = (int_part + frac_part).lstrip("0")
    return len(digits) if digits else 1


def last_digit_place(text: str) -> float | None:
    """Цена последней записанной цифры: «26» → 1, «0,056» → 0,001, «2600» → 100 (хвостовые нули целого не считаются)."""
    t = (text or "").strip().replace("−", "-").replace(",", ".")
    m = re.fullmatch(r"[-+]?(\d*)(?:\.(\d*))?(?:[eE]([-+]?\d+))?", t)
    if not m or not (m.group(1) or m.group(2)):
        return None
    exp = int(m.group(3) or 0)
    if m.group(2):
        return 10.0 ** (exp - len(m.group(2)))
    stripped = (m.group(1) or "").rstrip("0")
    return 10.0 ** (exp + len(m.group(1)) - len(stripped)) if m.group(1) else None


def precision_excessive(text: str, tolerance: float, sigfig_allowed: int = 2) -> bool:
    """Избыточно, если цифр больше разрешённого И цена последней цифры мельче допуска/20:
    «5,05» при ±0,95 — да; «105» при ±11 — нет (цена 1 ≥ 0,55); «0,52» при ±0,21 — нет (две цифры разрешены)."""
    place = last_digit_place(text)
    return place is not None and significant_figures(text) > sigfig_allowed and place < tolerance / 20


def grade_fields(specs: list[FieldSpec], key: list[KeyEntry], answers: dict[str, str]) -> Verdict:
    by_id = {k.id: k for k in key}
    results: list[FieldVerdict] = []
    for spec in specs:
        k = by_id[spec.id]
        raw = (answers.get(spec.id) or "").strip()
        max_points = k.points + k.points_error
        if not raw:
            results.append(FieldVerdict(spec.id, 0, max_points, "missing", "Поле пустое."))
            continue
        if spec.kind == "yesno":
            got = parse_yesno(raw)
            if got is None:
                results.append(FieldVerdict(spec.id, 0, max_points, "unparsed", "Ожидался ответ «да» или «нет»."))
            elif got == (k.value == "да"):
                results.append(FieldVerdict(spec.id, k.points, max_points, "ok", "Верно."))
            else:
                results.append(FieldVerdict(spec.id, 0, max_points, "wrong", f"Правильный ответ — «{k.value}»."))
            continue
        assert isinstance(k.value, float) and k.tolerance is not None
        if spec.kind == "number_with_error":
            val, err = parse_number_with_error(raw)
            val_text = raw.split("±")[0].split("+-")[0]
        else:
            val, err, val_text = parse_number(raw), None, raw
        if val is None:
            results.append(FieldVerdict(spec.id, 0, max_points, "unparsed", "Не удалось прочитать число."))
            continue
        diff = abs(val - k.value)
        penalties: list[str] = []
        unit = spec.unit.replace("_", "")           # «M_☉» → «M☉» в живом тексте
        glue = "" if unit[:1] in "°″′ᵐ" else " "     # градусы и секунды дуги пишутся без пробела
        with_unit = lambda x: f"{_fmt(x)}{glue}{unit}".rstrip().rstrip(".")   # «а. е.» не удваивает точку
        if diff <= k.tolerance:
            pts, status, comment = k.points, "ok", f"В пределах допуска ±{with_unit(k.tolerance)}."
        elif diff <= 2 * k.tolerance:
            pts, status, comment = k.points // 2, "near", f"Отклонение {with_unit(diff)} — больше допуска ±{_fmt(k.tolerance)}, но меньше двойного: половина баллов."
        else:
            pts, status, comment = 0, "wrong", f"Эталон {with_unit(k.value)}, допуск ±{_fmt(k.tolerance)}."
        if pts > 0 and precision_excessive(val_text, k.tolerance, k.sigfig_allowed):
            pts -= 1
            penalties.append(f"Избыточная точность: {significant_figures(val_text)} значащих цифр при допуске ±{_fmt(k.tolerance)} — минус 1 балл.")
        if spec.kind == "number_with_error":
            if err is None:
                penalties.append("Погрешность не указана — баллы за неё не начислены.")
            elif k.sigma is not None and k.sigma / 3 <= err <= 3 * k.sigma:
                pts += k.points_error
                comment += f" Погрешность ±{_fmt(err)} разумна (эталонная ±{_fmt(k.sigma)})."
            else:
                penalties.append(f"Погрешность ±{_fmt(err)} далека от эталонной ±{_fmt(k.sigma)} — баллы за неё не начислены.")
        results.append(FieldVerdict(spec.id, max(pts, 0), max_points, status, comment, penalties))
    total = sum(r.points for r in results)
    return Verdict(GRADER_VERSION, total, sum(r.max_points for r in results), results)


_SUP = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def _fmt(x: float, sig: int = 2) -> str:
    """Число с sig значащими цифрами и десятичной запятой; вне 10⁻⁶…10⁶ — вида 1,10·10³¹."""
    if x == 0 or not math.isfinite(x):
        return str(x)
    exp = math.floor(math.log10(abs(x)))
    if exp > 5 or exp < -6:
        mant = x / 10**exp
        return f"{mant:.{sig - 1}f}".replace(".", ",") + "·10" + str(exp).translate(_SUP)
    x = round(x, sig - 1 - exp)          # округление до sig значащих и при |x| ≥ 10^sig
    exp = math.floor(math.log10(abs(x))) if x else exp   # 9,96 → 10, а не 10,0
    decimals = max(sig - 1 - exp, 0)
    return f"{x:.{decimals}f}".replace(".", ",")


fmt = _fmt


def half_ulp(value: float, sig: int) -> float:
    """Половина единицы последней значащей цифры при записи value с sig значащими цифрами."""
    if value == 0:
        return 0.0
    return 0.5 * 10 ** (math.floor(math.log10(abs(value))) - sig + 1)


def allowed_sigfigs(tolerance: float, value: float) -> int:
    """Сколько значащих цифр разрешено в ответе: три, если допуск мельче 2 % значения, иначе две."""
    return 3 if tolerance / abs(value) < 0.02 else 2


def floor_tolerance(tolerance: float, value: float) -> float:
    """Допуск не меньше половины единицы последней разрешённой значащей цифры: честное округление не наказывается."""
    return max(tolerance, half_ulp(value, allowed_sigfigs(tolerance, value)))
