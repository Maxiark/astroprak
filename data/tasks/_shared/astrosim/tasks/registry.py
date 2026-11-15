"""Реестр семейств заданий: имя → модуль с FAMILY, FAMILY_LABEL, GENERATOR_VERSION, generate(seed), grade(package, answers).

Единственное место, где перечислены семейства; CLI, API и тесты берут список отсюда.
"""
from __future__ import annotations

from types import ModuleType

from astrosim.tasks import (
    cepheid_pl, comet_trails, descent_profile, galaxy_redshift, hubble_diagram, jet_superluminal,
    parallax_motion, rotation_mass, rv_binary, transit_depth, power_vertical,
)

FAMILIES: dict[str, ModuleType] = {
    m.FAMILY: m for m in (rv_binary, cepheid_pl, transit_depth, comet_trails, jet_superluminal,
                         descent_profile, galaxy_redshift, parallax_motion, rotation_mass, hubble_diagram, power_vertical,)
}


def get_family(name: str) -> ModuleType:
    try:
        return FAMILIES[name]
    except KeyError as exc:
        raise ValueError(f"неизвестное семейство: {name}") from exc
