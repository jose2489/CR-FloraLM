"""Manual-vs-GBIF agreement analysis.

Cross-checks the Manual's stated distribution (elevation + vertiente, extracted by
our pipeline) against real GBIF occurrence evidence. Two purposes:
  1. VALIDATION — what fraction of occurrences fall inside the stated range
     (an external check on extraction correctness).
  2. DISCOVERY — species whose occurrences systematically fall OUTSIDE the stated
     range: potential range extensions, under-documentation, or GBIF noise.

Uses DEM altitude at each occurrence (gbif_map), not GBIF's own elevation field.
"""
from __future__ import annotations

from ..query import retriever as R
from ..query import gbif_map
from ..store import local_store
from .. import config

# A spread of reasonably-collected species across families/elevations.
SAMPLE = [
    "Ocotea whitei", "Ocotea insularis", "Ocotea veraguensis", "Nectandra umbrosa",
    "Beilschmiedia pendula", "Aiouea costaricensis", "Cinnamomum brenesii",
    "Brosimum lactescens", "Castilla elastica", "Ficus schippii",
    "Chamaedorea pinnatifrons", "Calyptrogyne ghiesbreghtiana",
    "Calophyllum brasiliense", "Hypericum irazuense", "Banisteriopsis muricata",
]


def _norm(s: str) -> str:
    return gbif_map._norm(s)


def analyse(species: str, conn) -> dict | None:
    f = local_store.get(conn, species.replace(" ", "_"))
    if not f or f.elev_min is None:
        return None
    pts = gbif_map.get_points(species)
    pts = pts[pts["Altitud"].notna()] if not pts.empty else pts
    n = len(pts)
    if n == 0:
        return {"species": species, "family": f.family, "n": 0}

    emin, emax = f.elev_min, f.elev_max
    xlo = f.elev_outlier_min if f.elev_outlier_min is not None else emin
    xhi = f.elev_outlier_max if f.elev_outlier_max is not None else emax
    alt = pts["Altitud"]
    in_core = ((alt >= emin) & (alt <= emax)).mean()
    in_ext = ((alt >= xlo) & (alt <= xhi)).mean()
    below = (alt < xlo).mean()
    above = (alt > xhi).mean()

    # Robust comparison (Booth et al. 2014, Diversity & Distributions; Alhajeri &
    # Fourcade 2019, J. Biogeography): compare the GBIF CENTRE/core to the Manual
    # range, not the outlier-sensitive extremes. median_in = the GBIF median falls
    # inside the Manual range; core_overlap = the GBIF Q05–Q95 core overlaps it.
    med = float(alt.median())
    q05, q95 = float(alt.quantile(0.05)), float(alt.quantile(0.95))
    median_in = bool(xlo <= med <= xhi)
    core_overlap = bool(max(q05, xlo) <= min(q95, xhi))

    # vertiente agreement (points joined to a region carrying a Vertiente)
    vkeys = [_norm(v)[:4] for v in f.vertientes]
    vv = pts["Vertiente"].dropna()
    vmatch = (vv.apply(lambda x: any(k in _norm(x) for k in vkeys)).mean()
              if vkeys and len(vv) else None)

    return {
        "species": species, "family": f.family, "n": n,
        "manual": f"{emin}-{emax}", "manual_ext": f"{xlo}-{xhi}",
        "in_core": in_core, "in_ext": in_ext, "below": below, "above": above,
        "vmatch": vmatch, "median": med, "q05": q05, "q95": q95,
        "median_in": median_in, "core_overlap": core_overlap,
        "gbif_core": (int(q05), int(q95)),
    }


def sample_from_catalog(conn, n: int) -> list[str]:
    """A reproducible spread of species (with a stated elevation) across families."""
    from ..schema import Ficha
    rows = [Ficha.from_json(r["ficha_json"])
            for r in conn.execute("SELECT ficha_json FROM fichas")]
    rows = [f for f in rows if f.elev_min is not None]
    rows.sort(key=lambda f: (f.family, f.species))
    step = max(1, len(rows) // n)
    return [f.species for f in rows[::step]][:n]


def main(n: int = 1) -> None:
    import csv
    conn = local_store.connect(config.SQLITE_PATH)
    sample = sample_from_catalog(conn, n) if n > len(SAMPLE) else SAMPLE

    rows, seen = [], set()
    for i, sp in enumerate(sample, 1):
        key, accepted, syn = gbif_map.resolve_taxon(sp)
        if key is None or key in seen:             # no EXACT match, or dup taxon
            continue
        seen.add(key)
        r = analyse(sp, conn)
        if r:
            r["synonym"], r["accepted"] = syn, accepted
            rows.append(r)
        if i % 25 == 0:
            print(f"  ...{i}/{len(sample)} procesadas", flush=True)

    used = [r for r in rows if r.get("n", 0) >= 10]

    out = config.DATA_DIR / "eval"
    out.mkdir(exist_ok=True)
    with open(out / "manual_vs_gbif.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["species", "accepted", "synonym", "family",
            "n", "manual", "manual_ext", "in_core", "in_ext", "vmatch",
            "median", "q05", "q95", "median_in", "core_overlap"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in w.fieldnames})
    print(f"CSV → {out/'manual_vs_gbif.csv'}  ({len(rows)} spp con GBIF, "
          f"{len(used)} con n>=10)\n", flush=True)
    syn_rate = sum(1 for r in rows if r.get("synonym")) / max(1, len(rows))
    print(f"sinonimia Manual↔GBIF: {syn_rate*100:.0f}% de las especies", flush=True)

    if not used:
        return
    # ROBUST validation/discrepancy (median + Q05–Q95 core vs Manual range).
    med_in = sum(r["median_in"] for r in used) / len(used)
    core_ov = sum(r["core_overlap"] for r in used) / len(used)
    mc = sum(r["in_core"] for r in used) / len(used)
    vm = [r["vmatch"] for r in used if r["vmatch"] is not None]
    print(f"\nAGREGADO ROBUSTO (n>=10, {len(used)} spp):")
    print(f"  mediana GBIF dentro del rango Manual : {med_in*100:.0f}%   (validación)")
    print(f"  core Q05–Q95 solapa el rango Manual  : {core_ov*100:.0f}%")
    print(f"  ocurrencias en rango núcleo          : {mc*100:.0f}%   (nivel punto)")
    print(f"  concordancia de vertiente            : {sum(vm)/len(vm)*100:.0f}%")

    cand = [r for r in used if not r["median_in"]]      # robust discrepancy criterion
    cand.sort(key=lambda r: abs(r["median"]))
    print(f"\nCANDIDATOS REALES (mediana GBIF fuera del rango Manual, "
          f"{len(cand)} spp):")
    print(f"  {'species':26} {'fam':12} {'n':>4} {'manual':>9} {'GBIF core':>11} "
          f"{'med':>6} {'vert%':>5}")
    for r in cand:
        vmt = f"{r['vmatch']*100:.0f}" if r["vmatch"] is not None else "-"
        print(f"  {r['species'][:26]:26} {r['family'][:12]:12} {r['n']:4} "
              f"{r['manual_ext']:>9} {str(r['gbif_core']):>11} {r['median']:6.0f} {vmt:>5}")


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
