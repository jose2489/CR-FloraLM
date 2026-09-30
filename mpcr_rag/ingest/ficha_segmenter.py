"""Segment a Manual de Plantas de Costa Rica volume PDF into per-species fichas.

The Manual is a flora: each species entry ("ficha") has a near-regular anatomy:

    1. Header:        ``Aiouea costaricensis (Mez) Kosterm., <protologue>. 1938.``
    2. Synonyms+names ``Bellota costaricensis Mez, ... 1889. Ira, Mangle, Quizarra.``
    3. Morphology:    ``Arbusto o arbol, 3-30 m, las ramitas ...``
    4. Distribution:  ``Bosque muy humedo, ... 600-2500 m; ambas verts. ... Fl. ene. CR.``
    5. Discussion:    ``Aiouea costaricensis se reconoce por ...``

Only (1) the header and (4) the distribution paragraph are reliable anchors; ANY
other section may be absent for a given species. So segmentation keys solely on
those two, and every other field is independently optional.

The distribution paragraph later splits on its ``m;`` boundary into exactly the
``(habitat_raw, geographic_notes)`` pair that ``parser.build_ficha`` consumes, so
downstream extraction reuses the existing map pipeline verbatim.

Run as a module to segment the first PDF in ``config.CORPUS``:
    python -m mpcr_rag.ingest.ficha_segmenter
"""
from __future__ import annotations

import re

import fitz  # PyMuPDF

from ..schema import RawFicha


# --------------------------------------------------------------------------- #
# Block classification patterns
# --------------------------------------------------------------------------- #

# A species header opens a block as "<Genus> <epithet>" whose protologue carries a
# `volume: page` citation + a 4-digit year near the start — a discriminator no
# distribution paragraph or discussion shares. Unnamed entries are "<Genus> sp. N.".
_YEAR = r"(?:1[6789]\d\d|20\d\d)"
_HEADER_NAMED = re.compile(r"^([A-Z][a-záéíóúñ-]+)\s+([a-záéíóúñ-]{3,})\b")
_HEADER_SP = re.compile(r"^([A-Z][a-záéíóúñ]+)\s+sp\.\s*\d+")
_CITATION = re.compile(r"\d{1,3}(?:\(\d+[a-z]?\))?:\s*\d{1,4}")  # "46: 73" / "10(5): 49"
_YEAR_RE = re.compile(_YEAR)

# Capitalized Spanish words that open non-header blocks (distribution/morph/discussion).
_GENUS_STOP = {
    "Bosque", "Se", "Las", "Los", "El", "La", "En", "Por", "Como", "Esta", "Este",
    "Arbusto", "Árbol", "Arbol", "Hierba", "Bejuco", "Liana", "Planta", "Plantas",
    "Hojas", "Fls", "Frs", "Infl", "Infls", "Lámina", "Láminas", "Yemas", "Ramitas",
    "Vegetativamente", "Entre", "Sin", "Con", "Burger", "Werff",
}

# Genus header block: a lone capitalized word, then "Por <authors>" or genus stats.
_GENUS_HEADER = re.compile(r"^([A-Z][a-záéíóúñ]+)\s*\n\s*(?:Por\b|Ca\.\s)", re.M)

# Dichotomous-key block: carries leader dots.
_KEY_BLOCK = re.compile(r"\.\s\.\s\.|\.{4,}")

# Distribution paragraph detection. The elevation detector is deliberately loose
# (open/atypical ranges exist: "(100–)600–2500", "0–200+", "3200–"); precise min/max
# parsing happens later via parser._parse_elevation, not here.
_ELEV_M = re.compile(r"\d[\d\s().+?–—-]*\s*m\b")   # '?' = uncertain-elevation marker
# A real distribution block opens with a habitat/elevation term (NEVER a habit word)
# and carries a strong slope/endemism cue. NB: bare "ambas"/"región" are rejected —
# they appear in MORPHOLOGY ("ambas caras", "región basal"); require "ambas vert".
_FOREST_START = re.compile(r"^(Bosque|Sabana|Manglar|Páramo|Charral|Vegetaci|Matorral|Pastizal)")
_STRONG_DIST = re.compile(r"vert\.|verts\.|ambas\s+vert|END[ÉE]MIC|ENDEMIC")

# Morphology block opener (habit / description start).
_MORPH = re.compile(
    r"^(Arbusto|Árbol|Arbol|Hierba|Bejuco|Liana|Epífit|Hemiep|Sufrút|Planta|Hojas)"
)

# A leading clave number ("1 Ramitas ...", "3 Yemas ...") marks a key fragment.
_NUM_KEY = re.compile(r"^\d{1,2}\s+\S")

# Page furniture to drop.
_FURNITURE = re.compile(r"^\d+\s+Manual de Plantas|^MPCRv|Manual de Plantas de Costa Rica\s*$")


# Stray C0/C1 control characters injected by the OCR (e.g. "2500\x04 m") break
# regexes and would pollute embedded text + geo_parser input — strip them first.
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _clean(text: str) -> str:
    """Strip OCR control chars, then flatten linebreaks + hyphenation into prose."""
    text = _CTRL.sub("", text)
    text = text.replace("-\n", "").replace("­\n", "")
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def extract_blocks(pdf_path: str) -> list[tuple[int, str]]:
    """Return [(page_index, clean_block_text)] in reading order, furniture removed.

    Uses "dict" mode (keeps morphology and distribution as distinct blocks) and a
    plain reading-order sort by (y, x). The Manual is single-column with figures, so
    a y-first order is correct — an earlier (left/right-half, y) sort wrongly assumed
    two columns and scrambled pages where an image sits beside the text.
    """
    doc = fitz.open(pdf_path)
    out: list[tuple[int, str]] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        ph = page.rect.height
        blocks = []
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0:                    # skip image blocks
                continue
            txt = " ".join(s["text"] for line in b["lines"] for s in line["spans"])
            blocks.append((b["bbox"][0], b["bbox"][1], txt))
        blocks.sort(key=lambda t: (round(t[1]), t[0]))   # reading order: y then x
        for x0, y0, txt in blocks:
            t = txt.strip()
            if not t or _FURNITURE.search(t):
                continue
            # Running-name footers / PDF stamps: short text hugging top/bottom edge.
            if len(t) < 40 and (y0 < 100 or y0 > ph - 80):
                continue
            out.append((pno, _clean(t)))
    doc.close()
    return out


def _is_species_header(block: str) -> tuple[str, str, str] | None:
    """Return (genus, binomial, authority) if the block opens a species ficha."""
    m = _HEADER_SP.match(block)
    if m:
        genus = m.group(1)
        sp = re.match(r"^\S+\s+(sp\.\s*\d+)", block).group(1)
        return genus, f"{genus} {sp}", ""
    m = _HEADER_NAMED.match(block)
    if m and m.group(1) not in _GENUS_STOP:
        head = block[:140]                   # protologue sits at the very start
        if _CITATION.search(head) and _YEAR_RE.search(head):
            genus, epithet = m.group(1), m.group(2)
            authority = block[m.end(2):].split(".")[0].strip(" ,")
            return genus, f"{genus} {epithet}", authority
    return None


def segment(pdf_path: str, *, volume: str = "", family: str = "") -> list[RawFicha]:
    """Split a volume PDF into RawFicha records (one per species entry)."""
    blocks = extract_blocks(pdf_path)
    fichas: list[RawFicha] = []
    current: RawFicha | None = None
    current_genus = ""
    genus_desc = ""           # genus-level description, inherited by its species

    for pno, block in blocks:
        gm = _GENUS_HEADER.match(block)
        if gm and not _is_species_header(block):
            current_genus = gm.group(1)
            genus_desc = ""   # reset: new genus
            continue

        hdr = _is_species_header(block)
        if hdr:
            genus, binomial, authority = hdr
            if genus == current_genus or current_genus == "":
                current = RawFicha(
                    species=binomial, authority=authority, genus=genus,
                    header_block=block, volume=volume, family=family, page=pno,
                    genus_description=genus_desc,
                )
                fichas.append(current)
                continue

        if current is None:
            # genus preamble: capture the genus-level description (habit source)
            if not genus_desc and _MORPH.match(block):
                genus_desc = block
            continue  # still inside family/genus preamble or a key

        # Distribution = has elevation, does NOT open with a habit word (that's
        # morphology), and carries a strong slope/forest/endemism cue.
        is_dist = (bool(_ELEV_M.search(block)) and not _MORPH.match(block)
                   and bool(_STRONG_DIST.search(block) or _FOREST_START.match(block)))
        if not is_dist and (_KEY_BLOCK.search(block) or _NUM_KEY.match(block)):
            continue  # leftover dichotomous-key fragment

        current.blocks.append(block)
        if current.distribution_paragraph is None and is_dist:
            current.distribution_paragraph = block
        elif current.morphology is None and _MORPH.match(block):
            current.morphology = block
        elif current.distribution_paragraph is not None and current.discussion is None:
            current.discussion = block

    return _dedupe(fichas)


def _dedupe(fichas: list[RawFicha]) -> list[RawFicha]:
    """Collapse duplicate headers (running-footer repeats at genus transitions).

    Keep, per species, the entry with a distribution paragraph; else the richest.
    Drop empties (a footer that matched a header but captured nothing).
    """
    best: dict[str, RawFicha] = {}
    for f in fichas:
        if not f.blocks and not f.distribution_paragraph:
            continue
        cur = best.get(f.species)
        if cur is None:
            best[f.species] = f
            continue
        better = (bool(f.distribution_paragraph), len(f.blocks))
        if better > (bool(cur.distribution_paragraph), len(cur.blocks)):
            best[f.species] = f
    return list(best.values())


def _report(fichas: list[RawFicha]) -> None:
    n_dist = sum(1 for f in fichas if f.distribution_paragraph)
    print(f"{len(fichas)} fichas | {n_dist} with distribution paragraph "
          f"| {len(fichas) - n_dist} WITHOUT (missing-field cases)")
    for f in fichas:
        flag = "" if f.distribution_paragraph else "   <-- NO DIST PARAGRAPH"
        print(f"\n### {f.species}  (p.{f.page}){flag}")
        if f.distribution_paragraph:
            print(f"    {f.distribution_paragraph[:200]}")


if __name__ == "__main__":
    from .. import config
    entry = config.CORPUS[0]
    print(f"Segmenting {entry['family']} (Vol {entry['volume']})\n{entry['path']}\n")
    _report(segment(str(entry["path"]), volume=entry["volume"], family=entry["family"]))
