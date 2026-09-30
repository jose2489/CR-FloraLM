# Distribution Map Module — public API
from .ficha import DistributionFicha, EntityRef, ElevationRange
from .parser import build_ficha
from .renderer import generate_distribution_map
from .gazetteer import normalize_text, lookup

__all__ = [
    "DistributionFicha",
    "EntityRef",
    "ElevationRange",
    "build_ficha",
    "generate_distribution_map",
    "normalize_text",
    "lookup",
]
