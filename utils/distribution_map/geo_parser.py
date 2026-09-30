"""
geo_parser.py — Structured parser for Manual de Plantas geographic distribution blocks.

Implements the vertiente state machine described in CONTEXT_FOR_CLAUDE_CODE.md:
  - A vertiente marker (vert. Carib., vert. Pac., ambas verts.) sets active slope
    for ALL subsequent features until the next vertiente marker.
  - Feature tokens are classified by feature_type: cordillera, llanura, valle, fila,
    cerro, volcan, peninsula, region_informal, area_protegida, localidad.
  - Plural expansions: "Cords. de X, Y y Z" → multiple cordillera occurrences.
  - Sub-qualifiers: parenthetical content after a feature attaches to that feature.
  - Embedded protected areas: "región de X (P.N. Y)" → embedded_protected_areas.

Public API:
    parse_distribution_block(text: str) -> list[dict]

Each dict in the result:
    {
        "vertiente": "Caribe" | "Pacífico" | "ambas" | None,
        "qualifier": "N" | "S" | "E" | "O" | None,
        "feature_type": str,
        "feature_name": str,
        "sub_qualifier": str | None,
        "embedded_protected_areas": list[str],
        "raw_span": str,
    }
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


# ---------------------------------------------------------------------------
# Text normalisation (same pipeline as gazetteer.normalize_text)
# ---------------------------------------------------------------------------

def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return nfkd.encode("ascii", "ignore").decode("ascii")


def _norm(text: str) -> str:
    t = _strip_accents(str(text)).lower()
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"([a-z])- ([a-z])", r"\1\2", t)
    return t


# ---------------------------------------------------------------------------
# OCR pre-processing
# ---------------------------------------------------------------------------

def preprocess_ocr(text: str) -> str:
    """Normalize OCR artifacts before parsing."""
    # Normalize dashes to en-dash
    text = re.sub(r"—|‒|–", "–", text)
    # Fix common OCR confusions
    text = re.sub(r"\bF1\.", "Fl.", text)
    text = re.sub(r"\bFl\.(?=[^a-z])", "Fl.", text)
    text = re.sub(r"\bEN\s+D[ÉE]MICA\b", "ENDÉMICA", text, flags=re.IGNORECASE)
    # Rejoin hyphenated line breaks
    text = re.sub(r"-\n\s*", "", text)
    text = re.sub(r"\n", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Vertiente markers
# ---------------------------------------------------------------------------

_VERT_PATTERNS = [
    # Order matters: longer/more specific first.
    # Optional leading qualifier (N, S, E, O, NO, SE, centro …) before the vertiente word
    # handles cases like "S vert. Pac.", "N vert. Carib.", "centro vert. Pac."
    (re.compile(r"ambas\s+verts?\.?", re.I), "ambas"),
    (re.compile(r"(?:(?:[NSEO]{1,2}|centro|central)\.?\s+)?vert(?:iente)?\.?\s+carib(?:eña|eno|e)?\.?", re.I), "Caribe"),
    (re.compile(r"(?:(?:[NSEO]{1,2}|centro|central)\.?\s+)?vert(?:iente)?\.?\s+pac(?:if(?:ico|ica)?)?\.?", re.I), "Pacífico"),
    (re.compile(r"vertiente\s+carib(?:eña|eno|e)?", re.I), "Caribe"),
    (re.compile(r"vertiente\s+pac(?:if(?:ico|ica)?)?", re.I), "Pacífico"),
    (re.compile(r"carib(?:eña|eno)\b", re.I), "Caribe"),
]

def _detect_vertiente_at(text: str, pos: int) -> tuple[Optional[str], int] | None:
    """
    Check if a vertiente marker starts at `pos` in text.
    Returns (vertiente_name, end_pos) or None.
    """
    fragment = text[pos:]
    for pat, name in _VERT_PATTERNS:
        m = pat.match(fragment)
        if m:
            return name, pos + m.end()
    return None


# ---------------------------------------------------------------------------
# Qualifier detection (N, S, E, O before a feature name)
# ---------------------------------------------------------------------------

_QUALIFIER_PAT = re.compile(
    r"\b(N\.?|S\.?|E\.?|O\.?|NO\.?|NE\.?|SE\.?|SO\.?|norte|sur|este|oeste|norte)\s+",
    re.I,
)

_QUALIFIER_MAP = {
    "n": "N", "s": "S", "e": "E", "o": "O",
    "no": "NO", "ne": "NE", "se": "SE", "so": "SO",
    "norte": "N", "sur": "S", "este": "E", "oeste": "O",
}


# ---------------------------------------------------------------------------
# Protected-area abbreviation detection
# ---------------------------------------------------------------------------

_PA_ABBREV_PAT = re.compile(
    r"\b(?:"
    r"P\.?N\.?\s+\w[\w\s\.]*|"           # P.N. Name
    r"R\.?B\.?\s+\w[\w\s\.]*|"           # R.B. Name
    r"Z\.?P\.?\s+\w[\w\s\.]*|"           # Z.P. Name
    r"A\.?N\.?\s+\w[\w\s\.]*|"           # A.N. Name
    r"R\.?F\.?\s+\w[\w\s\.]*|"           # R.F. Name
    r"R\.?N\.?A\.?\s+\w[\w\s\.]*|"       # R.N.A. Name (Reserva Natural Absoluta)
    r"R\.?N\.?\s+\w[\w\s\.]*|"           # R.N. Name
    r"Parque\s+(?:Nacional|Internacional)\s+\w[\w\s]*|"
    r"Reserva\s+(?:Biológica|Forestal|Natural\s+Absoluta|Natural)\s+\w[\w\s]*|"
    r"Zona\s+Protectora\s+\w[\w\s]*"
    r")",
    re.I,
)

def _extract_embedded_pa(paren_content: str) -> list[str]:
    """Extract protected-area references from parenthetical content."""
    found = []
    for m in _PA_ABBREV_PAT.finditer(paren_content):
        name = m.group(0).strip().rstrip(".,;")
        if name:
            found.append(name)
    return found


# ---------------------------------------------------------------------------
# Feature-type classification
# ---------------------------------------------------------------------------

# Patterns for plural forms too (Cords., Llanuras, etc.)
_FEATURE_CLASSIFIERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bcords?\.?\s+(?:de\s+|del\s+)?", re.I), "cordillera"),
    (re.compile(r"\bcordilleras?\s+(?:de\s+|del\s+)?", re.I), "cordillera"),
    (re.compile(r"\bllanuras?\s+(?:de\s+|del\s+|de\s+los?\s+)?", re.I), "llanura"),
    (re.compile(r"\bllanura\s+(?:de\s+|del\s+)?", re.I), "llanura"),
    (re.compile(r"\bvalles?\s+(?:de\s+|del\s+)?", re.I), "valle"),
    (re.compile(r"\bfila(?:s)?\s+(?:de\s+|del\s+)?", re.I), "fila"),
    (re.compile(r"\bcerro(?:s)?\s+(?:de\s+|del\s+)?", re.I), "cerro"),
    (re.compile(r"\bvolc[aá]n(?:es)?\s+(?:de\s+|del\s+)?", re.I), "volcan"),
    (re.compile(r"\bpenínsula(?:s)?\s+(?:de\s+|del\s+)?|pen\.\s+(?:de\s+)?", re.I), "peninsula"),
    (re.compile(r"\bpen\.?\s+de\s+", re.I), "peninsula"),
    (re.compile(r"\bisla(?:s)?\s+(?:de\s+|del\s+)?", re.I), "isla"),
    (re.compile(r"\bpunta\s+", re.I), "cadena_menor"),
    # Protected areas — must come BEFORE region_informal
    (re.compile(r"\bP\.N\.\s+", re.I), "area_protegida"),
    (re.compile(r"\bR\.B\.\s+", re.I), "area_protegida"),
    (re.compile(r"\bZ\.P\.\s+", re.I), "area_protegida"),
    (re.compile(r"\bA\.N\.\s+", re.I), "area_protegida"),
    (re.compile(r"\bR\.F\.\s+", re.I), "area_protegida"),
    (re.compile(r"\bR\.N\.\s+", re.I), "area_protegida"),
    (re.compile(r"\bParque\s+(?:Nacional|Internacional)\s+", re.I), "area_protegida"),
    (re.compile(r"\bReserva\s+(?:Biol[oó]gica|Forestal|Natural)\s+", re.I), "area_protegida"),
    (re.compile(r"\bZona\s+Protectora\s+", re.I), "area_protegida"),
    # region_informal — "región de X", "vecindad de X"
    (re.compile(r"\bregi[oó]n\s+de(?:l)?\s+", re.I), "region_informal"),
    (re.compile(r"\bvecindad\s+de(?:l)?\s+", re.I), "localidad_buffer"),
    (re.compile(r"\bvecindades?\s+de(?:l)?\s+", re.I), "localidad_buffer"),
    # estacion biologica
    (re.compile(r"\bEstaci[oó]n\s+Biol[oó]gica\s+", re.I), "estacion_biologica"),
    (re.compile(r"\bEst\.\s+Biol\.\s+", re.I), "estacion_biologica"),
    # cuenca
    (re.compile(r"\bcuenca\s+del?\s+", re.I), "cuenca"),
    (re.compile(r"\br[íi]o\s+", re.I), "cuenca"),
]

_GAZETTEER_TYPE_MAP = {
    "cordillera":   "cordillera",
    "llanura":      "llanura",
    "valle":        "valle",
    "fila":         "fila",
    "peninsula":    "peninsula",
    "region_other": "region_informal",
    "park":         "area_protegida",
    "canton":       "localidad",
    "district":     "localidad",
    "vertiente":    "localidad",
}


_TODAS_CORDS = re.compile(
    r"todas\s+las\s+cords?\.?\s+principales?|todas\s+las\s+cordilleras?\s+principales?",
    re.I,
)
_TODA_VERT = re.compile(
    r"toda\s+la\s+vert(?:iente)?\.?\s+(?:carib|pac)",
    re.I,
)


def _classify_feature(fragment: str) -> tuple[str, str, str]:
    """
    Returns (feature_type, prefix_consumed, rest_of_fragment).
    feature_type is the type string.
    prefix_consumed is the matched prefix text (e.g. "Cord. de ").
    rest_of_fragment is what remains after the prefix.
    """
    # Special whole-phrase aliases that must be matched before any prefix classifier
    m = _TODAS_CORDS.match(fragment)
    if m:
        return "cordillera", m.group(0), fragment[m.end():]

    for pat, ftype in _FEATURE_CLASSIFIERS:
        m = pat.match(fragment)
        if m:
            return ftype, m.group(0), fragment[m.end():]

    # No prefix matched — try a direct gazetteer lookup on the name fragment
    # (handles proper names without geographic prefixes, e.g. "Baja Talamanca")
    # Import lazily to avoid circular dependency
    try:
        from .gazetteer import lookup as _gaz_lookup
        # Take up to the first delimiter character to extract the candidate name
        candidate = re.split(r'[,;(]', fragment)[0].strip().rstrip('.')
        if len(candidate) >= 4:
            hits = _gaz_lookup(candidate)
            for level, level_hits in hits.items():
                if level_hits:
                    ftype = _GAZETTEER_TYPE_MAP.get(level, "localidad")
                    if ftype != "localidad":
                        return ftype, "", fragment
    except Exception:
        pass

    return "localidad", "", fragment


# ---------------------------------------------------------------------------
# Name extractor — grab the feature name (up to next delimiter or qualifier)
# ---------------------------------------------------------------------------

def _extract_name(text: str) -> tuple[str, str]:
    """
    Extract the geographic name from the start of text.
    Stops at: comma, semicolon, period (sentence end), next vert. marker.
    Handles "y" joining items in a list at end.
    Returns (name, remainder).
    """
    # Stop at comma, semicolon, or period followed by space and uppercase (sentence end)
    # but NOT at "y" when it's a list connector (handled by plural expansion)
    m = re.match(
        r"([^,;(]+?)(?=\s*[,;(]|$|\.\s+[A-Z]|\bFl\.\b|\bFr\.\b|\bCR\b|\bNic\.\b|\bPan\.\b)",
        text,
        re.S,
    )
    if m:
        name = m.group(1).strip().rstrip(".")
        rest = text[m.end():].lstrip()
        return name, rest
    return text.strip().rstrip("."), ""


# ---------------------------------------------------------------------------
# Plural expansion
# ---------------------------------------------------------------------------

_LIST_JOINER = re.compile(r",\s*|\s+y\s+|\s+e\s+", re.I)

def _expand_plural_names(raw_names: str, feature_type: str) -> list[str]:
    """
    Split a comma/y-joined list of feature names into individual names.
    E.g. "Guanacaste, Tilarán y Central" → ["Guanacaste", "Tilarán", "Central"]
    """
    parts = _LIST_JOINER.split(raw_names.strip())
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Parenthetical content extraction
# ---------------------------------------------------------------------------

def _extract_parens(text: str, start: int) -> tuple[str, str]:
    """
    Starting from text[start] which should be '(', extract the content
    of the matching parenthesis. Returns (content, remainder_string).
    """
    if start >= len(text) or text[start] != "(":
        return "", text[start:]
    depth = 0
    end = start
    for i, ch in enumerate(text[start:], start):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    content = text[start + 1: end]
    remainder = text[end + 1:]
    return content, remainder


# ---------------------------------------------------------------------------
# Tokeniser: split text into a flat token stream preserving structure
# ---------------------------------------------------------------------------

# Known abbreviations that end with '.' but are NOT sentence boundaries
_ABBREV_NODOT = re.compile(
    r"\b(?:vert|verts|cord|cords|llanura|llanuras|pen|p\.n|r\.b|z\.p|a\.n|r\.f|r\.n"
    r"|est|biol|fig|sp|spp|cf|var|subsp|fl|fr|no|se|ne|so|n|s|e|o)\.",
    re.I,
)


def _tokenize_geo_block(text: str) -> list[str]:
    """
    Split a geographic distribution block at semicolons and at commas
    that are NOT inside parentheses. Returns a list of clause strings
    with vertiente markers intact.

    Does NOT split on periods (too many abbreviations).
    """
    clauses: list[str] = []
    current: list[str] = []
    depth = 0   # parenthesis depth

    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == ";" and depth == 0:
            part = "".join(current).strip()
            if part:
                clauses.append(part)
            current = []
        elif ch == "," and depth == 0:
            # Only split on comma if the remainder starts a NEW feature
            # (i.e. next non-space token is a vertiente marker or feature prefix)
            rest = text[i + 1:].lstrip()
            if _starts_new_feature(rest):
                part = "".join(current).strip()
                if part:
                    clauses.append(part)
                current = []
            else:
                current.append(ch)
        else:
            current.append(ch)
        i += 1

    part = "".join(current).strip()
    if part:
        clauses.append(part)

    return clauses


def _starts_new_feature(text: str) -> bool:
    """Return True if text begins with a vertiente marker or feature-type prefix."""
    for pat, _ in _VERT_PATTERNS:
        if pat.match(text):
            return True
    for pat, _ in _FEATURE_CLASSIFIERS:
        if pat.match(text):
            return True
    # Also: qualifier + feature (e.g. "N Cord.", "S Valle")
    qm = _QUALIFIER_PAT.match(text)
    if qm:
        rest = text[qm.end():]
        for pat, _ in _FEATURE_CLASSIFIERS:
            if pat.match(rest):
                return True
    return False


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_distribution_block(text: str) -> list[dict]:
    """
    Parse a geographic distribution block from Manual de Plantas text.

    Implements the vertiente state machine: a vertiente marker sets the
    active vertiente for all subsequent features until the next marker.

    Returns a list of occurrence dicts.
    """
    text = preprocess_ocr(text)

    occurrences: list[dict] = []
    active_vertiente: Optional[str] = None  # state machine

    clauses = _tokenize_geo_block(text)

    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue

        # Check if clause starts with a vertiente marker (may consume part)
        vert_result = _detect_vertiente_at(clause, 0)
        if vert_result:
            v_name, after_pos = vert_result
            active_vertiente = v_name
            # v_name "ambas" → both slopes
            clause = clause[after_pos:].strip().lstrip(":").strip()
            if not clause:
                continue

        # Now parse features within this clause
        _parse_clause_features(clause, active_vertiente, occurrences)

    return occurrences


def _parse_clause_features(
    clause: str,
    vertiente: Optional[str],
    out: list[dict],
) -> None:
    """
    Parse one clause (after vertiente marker stripped) into feature occurrences.
    Handles plural expansion (Cords. de X, Y y Z → 3 occurrences).
    """
    clause = clause.strip()
    if not clause:
        return

    # Check for a vertiente marker mid-clause (state change)
    # (handles "..., vert. Pac. Cord. de X, ...")
    vert_check = _detect_vertiente_at(clause, 0)
    if vert_check:
        # This will be caught at clause level — skip here
        pass

    # Detect qualifier prefix (N, S, etc.)
    qualifier: Optional[str] = None
    qm = _QUALIFIER_PAT.match(clause)
    if qm:
        q_raw = qm.group(1).rstrip(".").lower()
        qualifier = _QUALIFIER_MAP.get(q_raw)
        clause = clause[qm.end():]

    # Classify feature type
    feature_type, prefix, rest = _classify_feature(clause)

    if not rest and not prefix:
        # No recognizable feature — record as unresolved locality
        _add_occurrence(out, vertiente, qualifier, "localidad", clause.strip(), None, [])
        return

    # For area_protegida, consume the full name (no plural expansion expected)
    if feature_type == "area_protegida":
        name, remainder = _extract_name(rest)
        paren_content = ""
        embedded_pa: list[str] = []
        if remainder.lstrip().startswith("("):
            paren_content, remainder = _extract_parens(remainder.lstrip(), 0)
            embedded_pa = _extract_embedded_pa(paren_content)
        sub_qual = paren_content if paren_content and not embedded_pa else None
        _add_occurrence(out, vertiente, qualifier, feature_type,
                        (prefix + name).strip(), sub_qual, embedded_pa,
                        raw_span=prefix + name)
        # Continue parsing any remainder
        cont = remainder.lstrip(",; ").strip()
        if cont:
            _parse_clause_features(cont, vertiente, out)
        return

    # For plural-capable types, check if the rest contains a list
    # E.g. "Guanacaste, Tilarán y Central" after "Cords. de "
    # Strategy: take until next feature prefix or vertiente marker,
    # then split that sub-chunk by the list splitter.

    # Find where this feature's name list ends
    # (next feature type prefix OR new clause boundary OR parenthetical)
    name_chunk, remainder = _extract_name_chunk(rest, feature_type)

    # Extract trailing parenthetical (sub-qualifier / embedded PA)
    paren_content = ""
    embedded_pa: list[str] = []
    remainder_after = remainder
    if remainder.lstrip().startswith("("):
        paren_content, remainder_after = _extract_parens(remainder.lstrip(), 0)
        embedded_pa = _extract_embedded_pa(paren_content)

    sub_qual = paren_content if paren_content and not embedded_pa else None

    # Plural expansion
    names = _expand_plural_names(name_chunk, feature_type)

    # Special case: _TODAS_CORDS / _TODA_VERT consumed the whole fragment as
    # "prefix", leaving name_chunk empty.  Emit the matched phrase itself so
    # the gazetteer can resolve it via the "todas las cords. principales" alias.
    if not names and prefix and _TODAS_CORDS.match(prefix.strip()):
        _add_occurrence(
            out, vertiente, qualifier, feature_type,
            prefix.strip(), None, [],
            raw_span=prefix.strip(),
        )
        cont = remainder_after.lstrip(",; ").strip()
        if cont:
            _parse_clause_features(cont, vertiente, out)
        return

    for i, name in enumerate(names):
        name = name.strip().rstrip(".")
        if not name:
            continue
        # When the prefix already ends with "de" or "del", strip a leading
        # "de"/"del" from the individual name to avoid "de de Talamanca".
        if prefix:
            norm_prefix = prefix.strip().lower()
            if norm_prefix.endswith(" de") or norm_prefix.endswith(" del"):
                name = re.sub(r"^de[l]?\s+", "", name, flags=re.I)
        # Sub-qualifier and embedded PAs attach to the last name in the list
        # (matching Manual style "Cord. de X, Y y Z (P.N. XYZ)")
        sq = sub_qual if i == len(names) - 1 else None
        ep = embedded_pa if i == len(names) - 1 else []
        _add_occurrence(
            out, vertiente, qualifier, feature_type,
            (prefix.strip() + " " + name).strip() if prefix else name,
            sq, ep,
            raw_span=prefix + name_chunk,
        )

    # Recurse on remainder
    cont = remainder_after.lstrip(",; ").strip()
    if cont:
        _parse_clause_features(cont, vertiente, out)


def _extract_name_chunk(text: str, feature_type: str) -> tuple[str, str]:
    """
    Extract the name(s) portion of a feature clause — possibly a comma-separated
    list like "Guanacaste, Tilarán y Central". Stops at:
    - A new feature-type prefix (another Cord., Llanura de, etc.)
    - A vertiente marker
    - A parenthetical
    - End of string

    Returns (name_chunk, remainder).
    """
    # Scan for stop positions
    stop_pos = len(text)

    # Check for embedded parenthetical
    paren_m = re.search(r"\(", text)
    if paren_m:
        stop_pos = min(stop_pos, paren_m.start())

    # Check for another feature-type prefix
    for pat, _ in _FEATURE_CLASSIFIERS:
        # Only stop at prefix if there's at least some text before it
        for m in pat.finditer(text):
            if m.start() > 3:  # don't stop on first char
                stop_pos = min(stop_pos, m.start())
                break

    # Check for vertiente markers
    for pat, _ in _VERT_PATTERNS:
        m = pat.search(text)
        if m and m.start() > 3:
            stop_pos = min(stop_pos, m.start())

    # Check for period + uppercase (sentence end)
    sent_end = re.search(r"\.\s+[A-ZÁÉÍÓÚ]", text)
    if sent_end:
        stop_pos = min(stop_pos, sent_end.start() + 1)

    # Stop at any comma-separated token that is a known non-localidad gazetteer entity
    # (e.g. "Baja Talamanca" after "vecindad de Puerto Limón, ...")
    # This prevents proper names from being swallowed into prior feature's name list.
    try:
        from .gazetteer import lookup as _gaz_lookup
        for cm in re.finditer(r",\s*([A-ZÁÉÍÓÚ][^,;(]+?)(?=[,;(]|$)", text[:stop_pos]):
            candidate = cm.group(1).strip().rstrip(".")
            if len(candidate) >= 4:
                hits = _gaz_lookup(candidate)
                for level, level_hits in hits.items():
                    mapped = _GAZETTEER_TYPE_MAP.get(level, "localidad")
                    if mapped != "localidad" and level_hits and cm.start() > 0:
                        stop_pos = min(stop_pos, cm.start())
                        break
    except Exception:
        pass

    name_chunk = text[:stop_pos].strip().rstrip(",;")
    remainder = text[stop_pos:].strip()
    return name_chunk, remainder


def _add_occurrence(
    out: list[dict],
    vertiente: Optional[str],
    qualifier: Optional[str],
    feature_type: str,
    feature_name: str,
    sub_qualifier: Optional[str],
    embedded_pa: list[str],
    raw_span: str = "",
) -> None:
    feature_name = feature_name.strip().rstrip(".,;")
    if not feature_name:
        return
    out.append({
        "vertiente": vertiente,
        "qualifier": qualifier,
        "feature_type": feature_type,
        "feature_name": feature_name,
        "sub_qualifier": sub_qualifier,
        "embedded_protected_areas": embedded_pa,
        "raw_span": raw_span,
    })


# ---------------------------------------------------------------------------
# Convenience: extract just the feature names by type
# ---------------------------------------------------------------------------

def get_features_by_type(occurrences: list[dict], ftype: str) -> list[str]:
    return [o["feature_name"] for o in occurrences if o["feature_type"] == ftype]


def get_vertientes(occurrences: list[dict]) -> list[str]:
    seen: set[str] = set()
    result = []
    for o in occurrences:
        v = o.get("vertiente")
        if not v:
            continue
        candidates = ["Caribe", "Pacífico"] if v == "ambas" else [v]
        for c in candidates:
            if c not in seen:
                seen.add(c)
                result.append(c)
    return result


def get_all_protected_areas(occurrences: list[dict]) -> list[str]:
    """All PAs mentioned: direct area_protegida features + embedded in sub-qualifiers."""
    seen: set[str] = set()
    result = []
    for o in occurrences:
        if o["feature_type"] == "area_protegida":
            name = o["feature_name"]
            if name not in seen:
                seen.add(name)
                result.append(name)
        for pa in o.get("embedded_protected_areas", []):
            if pa not in seen:
                seen.add(pa)
                result.append(pa)
    return result
