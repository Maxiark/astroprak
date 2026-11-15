"""Общая сборка наблюдений: тексты и поля берутся из описания, физика — из модели."""
from __future__ import annotations

from astrosim.definitions import load_definition, render_content
from astrosim.tasks.base import FieldSpec, KeyEntry, TaskPackage, allowed_sigfigs, floor_tolerance, grade_fields


def assemble(family, version, seed, *, series, axes, plot, given, truth, tolerances, points, context):
    definition = load_definition(family)
    fields = [FieldSpec(**f) for f in definition["answers"]]
    key = [KeyEntry(f.id, truth[f.id], points[f.id], floor_tolerance(tolerances[f.id], truth[f.id]),
                    sigfig_allowed=allowed_sigfigs(tolerances[f.id], truth[f.id])) for f in fields]
    public = {"family_label": definition["title"], "statement": render_content(family, "statement", context),
              "data": {"series": series, "axes": axes}, "plot": plot,
              "fields": [f.__dict__ for f in fields], "tools": definition["tools"], "given": given}
    private = {"truth": truth, "key": [k.__dict__ for k in key],
               "solution": render_content(family, "solution", context)}
    return TaskPackage(family, version, seed, public, private)


def grade(package, answers):
    return grade_fields([FieldSpec(**f) for f in package.public["fields"]],
                        [KeyEntry(**k) for k in package.private["key"]], answers)
