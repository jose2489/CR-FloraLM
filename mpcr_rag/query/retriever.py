"""Retrieval for the two query patterns.

Pattern A — species → ficha: a keyed fetch by vector id (not semantic).
Pattern B — geospatial question: a Pinecone *metadata filter* (the discriminating
work) + semantic rank over distribution-paragraph vectors. Structured constraints
(habit, elevation window, vertiente, region, flowering month, endemism) are turned
into a Pinecone filter; elevation uses range *overlap*.

Hits are hydrated into full Ficha records from the SQLite store for citable answers.
"""
from __future__ import annotations

from .. import config
from ..schema import Ficha
from ..store import local_store, pinecone_client as pc


def pattern_a(species: str, conn=None) -> Ficha | None:
    """Species name → full Ficha (keyed lookup via the local store)."""
    conn = conn or local_store.connect(config.SQLITE_PATH)
    return local_store.get(conn, species.replace(" ", "_"))


def build_filter(
    *,
    habit: str | None = None,
    elev_lo: int | None = None,
    elev_hi: int | None = None,
    vertiente: str | None = None,
    region: str | None = None,
    forest_type: str | None = None,
    family: str | None = None,
    flowering_month: int | None = None,
    endemic: bool | None = None,
) -> dict:
    """Compose a Pinecone metadata filter. Elevation = range overlap."""
    clauses: list[dict] = []
    if habit:
        clauses.append({"habits": {"$in": [habit]}})
    # Membership uses the OUTLIER-EXTENDED (effective) range so occasional records
    # are not missed; ranking (relevance) still uses the core range for specificity.
    if elev_hi is not None:
        clauses.append({"elev_min_eff": {"$lte": elev_hi, "$gte": 0}})
    if elev_lo is not None:
        clauses.append({"elev_max_eff": {"$gte": elev_lo}})
    if vertiente:
        clauses.append({"vertientes": {"$in": [vertiente]}})
    if region:
        clauses.append({"regions": {"$in": [region]}})
    if forest_type:
        clauses.append({"forest_types": {"$in": [forest_type]}})
    if family:
        clauses.append({"family": {"$eq": family}})
    if flowering_month is not None:
        clauses.append({"flowering_months": {"$in": [str(flowering_month)]}})
    if endemic is not None:
        clauses.append({"endemic": endemic})
    if not clauses:
        return {}
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _eff_bounds(f: Ficha) -> tuple[int | None, int | None]:
    """Outlier-extended elevation range ('where it has ever been recorded')."""
    lo = f.elev_outlier_min if f.elev_outlier_min is not None else f.elev_min
    hi = f.elev_outlier_max if f.elev_outlier_max is not None else f.elev_max
    return lo, hi


def is_occasional(f: Ficha, lo: int | None, hi: int | None) -> bool:
    """True when the query window only meets the species via its outlier zone
    (core range does not overlap) — i.e. an 'occasional' match to flag in answers."""
    _, _, core_inter = elev_relevance(f, lo, hi)
    return core_inter <= 0


def elev_relevance(f: Ficha, lo: int | None, hi: int | None) -> tuple[float, float, float]:
    """Interval overlap of the species band [emin,emax] with the query window [lo,hi].

    Returns (containment, coverage, intersection):
      containment = fraction of the SPECIES band inside the window (specificity —
                    separates a true band-dweller from a generalist that passes through)
      coverage    = fraction of the WINDOW the species covers
    """
    if lo is None and hi is None or f.elev_min is None or f.elev_max is None:
        return 0.0, 0.0, 0.0
    lo = f.elev_min if lo is None else lo
    hi = f.elev_max if hi is None else hi
    inter = max(0, min(hi, f.elev_max) - max(lo, f.elev_min))
    rng = max(1, f.elev_max - f.elev_min)
    window = max(1, hi - lo)
    return inter / rng, inter / window, float(inter)


def relevance(f: Ficha, constraints: dict, semantic: float) -> float:
    """Composite rank for a Pattern-B hit.

    When an elevation window is given, structured overlap dominates (interpretable);
    the semantic score is only a small free-text tiebreak. Hooks remain for a future
    GBIF-density 'most likely' term (see notes) — Manual abundance is NOT used: the
    Manual does not encode species-level ecological abundance.
    """
    lo, hi = constraints.get("elev_lo"), constraints.get("elev_hi")
    if lo is not None or hi is not None:
        contain, cover, _ = elev_relevance(f, lo, hi)
        return 0.6 * contain + 0.3 * cover + 0.1 * semantic
    return semantic


def filter_all(
    conn=None,
    *,
    habit: str | None = None,
    elev_lo: int | None = None,
    elev_hi: int | None = None,
    vertiente: str | None = None,
    region: str | None = None,
    forest_type: str | None = None,
    family: str | None = None,
    flowering_month: int | None = None,
    endemic: bool | None = None,
) -> list[Ficha]:
    """Exhaustive structured-only candidate set: no Pinecone, no top_k cap, no
    semantic rank. For deterministic superlative selection ("la especie MÁS X"),
    where the answer must come from the FULL filtered population, not a
    semantically-ranked top-k slice."""
    conn = conn or local_store.connect(config.SQLITE_PATH)
    rows = [Ficha.from_json(r["ficha_json"]) for r in conn.execute("SELECT ficha_json FROM fichas")]

    out: list[Ficha] = []
    for f in rows:
        if habit and habit not in f.habits:
            continue
        if vertiente and vertiente not in f.vertientes:
            continue
        if region and region not in f.regions:
            continue
        if forest_type and forest_type not in f.forest_types:
            continue
        if family and family != f.family:
            continue
        if flowering_month is not None and flowering_month not in f.flowering_months:
            continue
        if endemic is not None and f.endemic_cr != endemic:
            continue
        if elev_lo is not None or elev_hi is not None:
            elo, ehi = _eff_bounds(f)
            eff_lo = elo if elev_lo is None else elev_lo
            eff_hi = ehi if elev_hi is None else elev_hi
            if elo is None or ehi is None or min(eff_hi, ehi) - max(eff_lo, elo) <= 0:
                continue
        out.append(f)
    return out


def pattern_b(
    query_text: str,
    *,
    top_k: int = 25,
    strict_overlap: bool = True,
    conn=None,
    index=None,
    **constraints,
) -> list[tuple[Ficha, float]]:
    """Geospatial question → (Ficha, relevance) list, structured-overlap ranked.

    With an elevation window, results are ranked by interpretable band-overlap (not the
    near-flat semantic score) and boundary-only touches are dropped (strict_overlap).
    """
    conn = conn or local_store.connect(config.SQLITE_PATH)
    flt = build_filter(**constraints)
    hits = pc.search(query_text, top_k=top_k, flt=flt, index=index)
    lo, hi = constraints.get("elev_lo"), constraints.get("elev_hi")
    has_window = lo is not None or hi is not None

    scored: list[tuple[Ficha, float]] = []
    for h in hits:
        f = local_store.get(conn, h["id"])
        if not f:
            continue
        if has_window and strict_overlap:
            elo, ehi = _eff_bounds(f)
            eff_lo = elo if lo is None else lo
            eff_hi = ehi if hi is None else hi
            if elo is None or ehi is None or min(eff_hi, ehi) - max(eff_lo, elo) <= 0:
                continue  # no real overlap even on the outlier-extended range
        scored.append((f, relevance(f, constraints, h["score"])))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


if __name__ == "__main__":
    idx = pc.ensure_index()
    conn = local_store.connect(config.SQLITE_PATH)

    print("=== Pattern A: 'Ocotea gomezii' ===")
    f = pattern_a("Ocotea gomezii", conn=conn)
    if f:
        print(f"  {f.species} [{f.elev_min}-{f.elev_max} m] {f.habits} "
              f"vert={f.vertientes} regions={f.regions[:3]}…")

    print("\n=== Pattern B: 'arbustos que crecen entre 150 y 300 m' "
          "(filter: habit=arbusto, 150–300 m) ===")
    res = pattern_b("arbustos de tierras bajas", habit="arbusto",
                    elev_lo=150, elev_hi=300, conn=conn, index=idx)
    for f, score in res:
        print(f"  {score:.3f}  {f.species:30} [{f.elev_min}-{f.elev_max} m] "
              f"{'ENDÉMICA' if f.endemic_cr else ''}")

    print("\n=== Pattern B: 'especies endémicas sobre 2000 m en vert. Pacífico' ===")
    res = pattern_b("bosque de altura, robledales", elev_lo=2000,
                    vertiente="Pacífico", endemic=True, conn=conn, index=idx)
    for f, score in res:
        print(f"  {score:.3f}  {f.species:30} [{f.elev_min}-{f.elev_max} m] {f.vertientes}")
