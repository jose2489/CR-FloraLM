"""
gazetteer.py — Entity gazetteer: text aliases → canonical geographic entities.

Replaces the 137-regex translation table with a deterministic longest-match
lookup against a CSV of known entities and their aliases. Designed to be
ordering-insensitive: no "more specific patterns must precede broader ones".

Lookup pipeline:
  1. normalize_text()  — NFKD → ASCII → lowercase → apply OCR corrections
  2. Longest-match scan over the alias index
  3. rapidfuzz fuzzy fallback for remaining unmatched fragments
  4. LLM fallback hook (optional, via parser._llm_resolve)
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
from rapidfuzz import process as fz_process

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_GAZETTEER_DIR  = Path(__file__).parent.parent.parent / "data_raw" / "gazetteer"
ENTITIES_CSV    = _GAZETTEER_DIR / "entities.csv"
CORRECTIONS_CSV = _GAZETTEER_DIR / "ocr_corrections.csv"

# MOBOT Gazetteer of Costa Rican Plant-Collecting Locales
_MOBOT_GPKG = Path(
    r"C:\Users\Jose\Documents\Tesis\raw_data\Gazetteer\cr_gazetteer.gpkg"
)


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _load_corrections() -> list[tuple[str, str]]:
    """Return (raw, corrected) pairs sorted longest-raw-first."""
    if not CORRECTIONS_CSV.exists():
        return []
    df = pd.read_csv(CORRECTIONS_CSV, comment="#")
    pairs = [(str(r["raw"]).strip(), str(r["corrected"]).strip())
             for _, r in df.iterrows()
             if str(r.get("raw", "")).strip()]
    # Apply longest substitution first to avoid partial clobbers
    pairs.sort(key=lambda x: -len(x[0]))
    return pairs


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return nfkd.encode("ascii", "ignore").decode("ascii")


def normalize_text(text: str) -> str:
    """
    Full normalisation pipeline:
      NFKD → strip accents → lowercase → collapse whitespace →
      line-break hyphens → OCR corrections.

    The same function is used on both the input text and the alias strings
    in the CSV so comparisons are always apples-to-apples.
    """
    t = _strip_accents(str(text))
    t = t.lower()
    t = re.sub(r"\s+", " ", t).strip()
    # Re-join words split by OCR line-break hyphens: "tortu- guero" → "tortuguero"
    t = re.sub(r"([a-z])- ([a-z])", r"\1\2", t)
    for raw, corrected in _load_corrections():
        t = t.replace(raw, corrected)
    return t


# ---------------------------------------------------------------------------
# Gazetteer index
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _load_entities() -> pd.DataFrame:
    if not ENTITIES_CSV.exists():
        raise FileNotFoundError(f"Gazetteer CSV not found: {ENTITIES_CSV}")
    df = pd.read_csv(ENTITIES_CSV, dtype=str).fillna("")
    return df


def _build_alias_index() -> list[tuple[str, str, str, str, str, str]]:
    """
    Build a flat list of (normalized_alias, canonical_name, hierarchy_level,
    target_shapefile, target_attribute, target_value) sorted longest-alias-first.

    Longest-first ensures "toda la vert. carib" beats "vert. carib" when both
    appear as substrings of the same text.
    """
    df = _load_entities()
    entries: list[tuple[str, str, str, str, str, str]] = []
    for _, row in df.iterrows():
        canonical    = row["canonical_name"].strip()
        level        = row["hierarchy_level"].strip()
        shapefile    = row["target_shapefile"].strip()
        attribute    = row["target_attribute"].strip()
        value        = row["target_value"].strip()
        raw_aliases  = row["aliases"].strip()
        if not raw_aliases:
            continue
        for alias in raw_aliases.split("|"):
            norm = normalize_text(alias.strip())
            if norm:
                entries.append((norm, canonical, level, shapefile, attribute, value))
    # Sort by (length DESC, alias, level) — keeps same-alias/same-level entries
    # adjacent so the grouped-match logic in lookup() can collect them together.
    entries.sort(key=lambda x: (-len(x[0]), x[0], x[2]))
    return entries


# Cache the built index (called once per process)
@lru_cache(maxsize=None)
def _alias_index() -> list[tuple[str, str, str, str, str, str]]:
    return _build_alias_index()


# ---------------------------------------------------------------------------
# Public lookup
# ---------------------------------------------------------------------------

def lookup(text: str) -> dict[str, list[dict]]:
    """
    Scan normalized text for all known entity aliases.

    Returns a dict keyed by hierarchy_level, each containing a list of
    matched entity dicts:
      {canonical_name, hierarchy_level, target_shapefile,
       target_attribute, target_value, source_span}

    Longest-match rule is applied *per hierarchy level*: once a span is consumed
    within a level, a shorter alias at the same level cannot claim it. But a
    different level (e.g. canton vs region) CAN match the same span — this lets
    "Puriscal" match both region "Puriscal - Los Santos" and canton "Puriscal"
    from the same text fragment.
    """
    norm = normalize_text(text)
    index = _alias_index()

    # consumed positions tracked per hierarchy_level separately
    consumed_by_level: dict[str, set[int]] = {}
    # track (canonical_name, hierarchy_level) to avoid duplicate entries
    seen_entities: set[tuple[str, str]] = set()

    matched: list[dict] = []

    # The index is sorted by (-len, alias_norm, level) so entries sharing the
    # same (alias_norm, level) are adjacent. We process them as a group so that
    # ONE alias that maps to N entities (e.g. "todas las cordilleras principales"
    # → all 4 cordilleras) matches ALL N entities at the same span position
    # before consuming that span.
    i = 0
    while i < len(index):
        alias_norm, canonical_0, level_0, _, _, _ = index[i]

        # Collect all consecutive entries with the same alias + level
        j = i
        group: list[tuple] = []
        while j < len(index) and index[j][0] == alias_norm and index[j][2] == level_0:
            group.append(index[j])
            j += 1

        consumed = consumed_by_level.setdefault(level_0, set())
        start = 0
        while True:
            pos = norm.find(alias_norm, start)
            if pos == -1:
                break
            end = pos + len(alias_norm)
            span_positions = set(range(pos, end))

            if not (span_positions & consumed):
                # Always consume the span to block shorter aliases at this level,
                # even when all entities in the group were already seen.
                consumed |= span_positions
                for (an, cn, lv, sf, at, tv) in group:
                    entity_key = (cn, lv)
                    if entity_key not in seen_entities:
                        matched.append({
                            "canonical_name":   cn,
                            "hierarchy_level":  lv,
                            "target_shapefile": sf,
                            "target_attribute": at,
                            "target_value":     tv,
                            "source_span":      text[pos:end] if pos < len(text) else an,
                        })
                        seen_entities.add(entity_key)
            start = end

        i = j

    # Group by hierarchy_level
    result: dict[str, list[dict]] = {}
    for m in matched:
        result.setdefault(m["hierarchy_level"], []).append(m)

    return result


def lookup_parks(text: str, pa_names: list[str]) -> list[str]:
    """
    Return subset of `pa_names` whose normalized name appears in text.
    Handles the "P.N. Carara" → "Parque Nacional Carara" expansion via
    OCR corrections (which expand "parque nacional" from "p.n.").
    Short names (<5 chars) require word boundaries.
    """
    norm = normalize_text(text)
    matched = []
    for name in pa_names:
        norm_name = normalize_text(name)
        if len(norm_name) < 5:
            pat = r"\b" + re.escape(norm_name) + r"\b"
            if re.search(pat, norm):
                matched.append(name)
        else:
            if norm_name in norm:
                matched.append(name)
    return matched


def fuzzy_lookup(tokens: list[str], cutoff: int = 88) -> dict[str, list[dict]]:
    """
    Try to fuzzy-match a list of unresolved text tokens against all known
    canonical names. Returns the same structure as lookup().

    Only tokens with score >= cutoff are accepted.
    """
    df = _load_entities()
    candidates = df["canonical_name"].dropna().unique().tolist()
    result: dict[str, list[dict]] = {}

    for token in tokens:
        norm_token = normalize_text(token)
        if len(norm_token) < 4:
            continue
        match = fz_process.extractOne(
            norm_token,
            [normalize_text(c) for c in candidates],
            score_cutoff=cutoff,
        )
        if match is None:
            continue
        matched_norm, score, idx = match
        row = df[df["canonical_name"] == candidates[idx]].iloc[0]
        entry = {
            "canonical_name":   row["canonical_name"],
            "hierarchy_level":  row["hierarchy_level"],
            "target_shapefile": row["target_shapefile"],
            "target_attribute": row["target_attribute"],
            "target_value":     row["target_value"],
            "source_span":      token,
            "fuzzy_score":      score,
        }
        result.setdefault(row["hierarchy_level"], []).append(entry)

    return result


# ---------------------------------------------------------------------------
# MOBOT Gazetteer of Costa Rican Plant-Collecting Locales
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _load_mobot_points():
    """Load MOBOT gazetteer points layer (cached). Returns GeoDataFrame or None."""
    if not _MOBOT_GPKG.exists():
        return None
    try:
        import geopandas as gpd
        return gpd.read_file(str(_MOBOT_GPKG), layer="gazetteer_points")
    except Exception as e:
        print(f"  [WARN] Could not load MOBOT gazetteer: {e}")
        return None


@lru_cache(maxsize=None)
def _load_mobot_buffers():
    """Load MOBOT gazetteer 10km buffer polygons layer (cached)."""
    if not _MOBOT_GPKG.exists():
        return None
    try:
        import geopandas as gpd
        return gpd.read_file(str(_MOBOT_GPKG), layer="gazetteer_buffer10km")
    except Exception as e:
        print(f"  [WARN] Could not load MOBOT gazetteer buffers: {e}")
        return None


def lookup_mobot_locality(
    name: str,
    cutoff: int = 82,
    region_mode: bool = False,
) -> Optional[dict]:
    """
    Look up a locality name in the MOBOT Gazetteer.

    Matching strategy:
      1. Exact normalized match
      2. Query is substring of gazetteer name (shortest match wins)
      3. All query words appear in gazetteer name
      4. rapidfuzz fuzzy match at cutoff

    When region_mode=True, returns a dict with row_indices (list of ALL
    matching rows) so the caller can union multiple buffers for a region.

    Returns dict with keys: name, slope, province, canton, elev_min_m,
    elev_max_m, description, row_index (int), row_indices (list), or None.
    """
    pts = _load_mobot_points()
    if pts is None:
        return None

    norm_query = normalize_text(name)
    if len(norm_query) < 3:
        return None

    names_norm = [normalize_text(str(n)) for n in pts["name"].fillna("")]

    # In region_mode, collect ALL rows where query appears in name, then return
    # a representative dict with all indices
    if region_mode:
        matching_indices = [
            i for i, nn in enumerate(names_norm)
            if norm_query in nn or nn == norm_query
        ]
        if matching_indices:
            rep = pts.iloc[matching_indices[0]]
            result = _mobot_row_to_dict(rep, matching_indices[0])
            result["row_indices"] = matching_indices
            return result
        # Fallback: fuzzy with lower threshold for region
        if len(norm_query) >= 5:
            match = fz_process.extractOne(norm_query, names_norm, score_cutoff=75)
            if match is not None:
                _, score, idx = match
                result = _mobot_row_to_dict(pts.iloc[idx], idx)
                result["row_indices"] = [idx]
                return result
        return None

    # Single-point mode
    # 1. Exact match
    for i, nn in enumerate(names_norm):
        if nn == norm_query:
            r = _mobot_row_to_dict(pts.iloc[i], i)
            r["row_indices"] = [i]
            return r

    # 2. Shortest substring match
    best_sub: Optional[tuple[int, int]] = None
    for i, nn in enumerate(names_norm):
        if norm_query in nn:
            if best_sub is None or len(nn) < best_sub[0]:
                best_sub = (len(nn), i)
    if best_sub is not None:
        r = _mobot_row_to_dict(pts.iloc[best_sub[1]], best_sub[1])
        r["row_indices"] = [best_sub[1]]
        return r

    # 3. All query words in gazetteer name
    query_words = [w for w in norm_query.split() if len(w) > 3]
    if query_words:
        for i, nn in enumerate(names_norm):
            if all(w in nn for w in query_words):
                r = _mobot_row_to_dict(pts.iloc[i], i)
                r["row_indices"] = [i]
                return r

    # 4. Fuzzy
    if len(norm_query) >= 5:
        match = fz_process.extractOne(norm_query, names_norm, score_cutoff=cutoff)
        if match is not None:
            _, score, idx = match
            r = _mobot_row_to_dict(pts.iloc[idx], idx)
            r["row_indices"] = [idx]
            return r

    return None


def get_mobot_buffers(row_indices: list[int]):
    """
    Return a GeoDataFrame with 10km buffer polygons for the given row indices.
    Returns None if no buffers found.
    """
    import geopandas as gpd
    import pandas as pd

    buf = _load_mobot_buffers()
    if buf is None:
        return None
    valid = [i for i in row_indices if i < len(buf)]
    if not valid:
        return None
    return buf.iloc[valid]


def get_mobot_buffer(row_index: int):
    """Return the 10km buffer polygon GeoDataFrame row for a single gazetteer entry."""
    return get_mobot_buffers([row_index])


def _mobot_row_to_dict(row, idx: int) -> dict:
    return {
        "name":        row["name"],
        "slope":       row.get("slope", ""),
        "province":    row.get("province", ""),
        "canton":      row.get("canton", ""),
        "elev_min_m":  row.get("elev_min_m"),
        "elev_max_m":  row.get("elev_max_m"),
        "description": row.get("description", ""),
        "row_index":   idx,
        "row_indices": [idx],
    }


def lookup_mobot_localities_batch(
    names: list[str],
    cutoff: int = 82,
    region_mode: bool = False,
) -> dict[str, Optional[dict]]:
    """Look up multiple locality names, return {name: result_or_None}."""
    return {name: lookup_mobot_locality(name, cutoff, region_mode) for name in names}
