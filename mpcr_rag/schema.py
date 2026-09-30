"""Core data structures for the MPCR-RAG subproject.

``RawFicha`` is the raw output of segmentation (PDF blocks grouped per species).
``Ficha`` is the fully-extracted, queryable record stored in SQLite + (partly) in
the Pinecone index. Every field on ``Ficha`` is independently nullable: Manual
fichas are NOT uniform, so no missing section may break the parse.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class RawFicha:
    """Raw per-species segmentation output, before field extraction."""

    species: str                         # accepted binomial, e.g. "Aiouea obscura"
    authority: str = ""
    genus: str = ""
    header_block: str = ""               # binomial + protologue + synonyms + common names
    morphology: str | None = None        # may be absent
    distribution_paragraph: str | None = None   # the geo gold; may be absent
    discussion: str | None = None        # "se reconoce por ..."; may be absent
    genus_description: str = ""          # genus-level description (for habit inheritance)
    volume: str = ""
    family: str = ""
    page: int = -1
    blocks: list[str] = field(default_factory=list)   # all blocks captured for this ficha


@dataclass
class Ficha:
    """Fully-extracted, queryable species record."""

    # identity ----------------------------------------------------------- segmenter
    species: str
    authority: str = ""
    genus: str = ""
    family: str = ""
    synonyms: list[str] = field(default_factory=list)
    volume: str = ""
    pages: str = ""                       # provenance for citations

    # geospatial — DETERMINISTIC (geo_parser / parser) ------- the paper's core
    elev_min: int | None = None
    elev_max: int | None = None
    elev_outlier_min: int | None = None   # "(100–)400–1850" → occasional low of 100
    elev_outlier_max: int | None = None
    vertientes: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    forest_types: list[str] = field(default_factory=list)
    distribution_paragraph: str = ""      # embedded vector text

    # enrichment — regex / LLM ("available for answers") ----------------------
    habits: list[str] = field(default_factory=list)  # árbol / arbusto / hierba / epífita / bejuco
    common_names: list[str] = field(default_factory=list)
    endemic_cr: bool = False
    global_range: str | None = None       # e.g. "CR y O Pan."
    flowering_months: list[int] = field(default_factory=list)
    fruiting_months: list[int] = field(default_factory=list)
    uses: str | None = None

    full_text: str = ""                   # complete ficha prose, for hydration/citation

    # ---- serialization helpers -------------------------------------------------
    @property
    def vector_id(self) -> str:
        """Stable id shared between Pinecone and the SQLite store."""
        return self.species.replace(" ", "_")

    def metadata(self) -> dict:
        """Filterable subset stored in Pinecone metadata (kept small)."""
        return {
            "species": self.species,
            "genus": self.genus,
            "family": self.family,
            "volume": self.volume,
            "pages": self.pages,
            "elev_min": self.elev_min if self.elev_min is not None else -1,
            "elev_max": self.elev_max if self.elev_max is not None else -1,
            "vertientes": self.vertientes,
            "regions": self.regions,
            "forest_types": self.forest_types,
            "habits": self.habits,
            "endemic_cr": self.endemic_cr,
            "flowering_months": self.flowering_months,
        }

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "Ficha":
        return cls(**json.loads(s))
