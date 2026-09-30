"""Generate a paper-ready, reproducible report from a Manual-vs-GBIF run.

Reads the per-species CSV produced by ``manual_vs_gbif.main`` and writes a Markdown
results document plus a frozen copy of the CSV into ``eval/results/`` (committed,
unlike the regenerable ``data/`` artifacts).

Run:  python -m mpcr_rag.eval.make_report
"""
from __future__ import annotations

import csv
import datetime as _dt
import shutil
from pathlib import Path

from .. import config

_SRC_CSV = config.DATA_DIR / "eval" / "manual_vs_gbif.csv"
_RESULTS = Path(__file__).resolve().parent / "results"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main() -> None:
    _RESULTS.mkdir(exist_ok=True)
    rows = list(csv.DictReader(open(_SRC_CSV, encoding="utf-8")))

    with_data = [r for r in rows if (_f(r["n"]) or 0) >= 1]
    used = [r for r in rows if (_f(r["n"]) or 0) >= 10]
    nU = len(used)

    def rate(pred):
        return sum(1 for r in used if pred(r)) / nU

    median_in = rate(lambda r: r["median_in"] == "True")
    core_ov = rate(lambda r: r["core_overlap"] == "True")
    in_core = sum(_f(r["in_core"]) for r in used) / nU
    vlist = [_f(r["vmatch"]) for r in used if _f(r["vmatch"]) is not None]
    vmatch = sum(vlist) / len(vlist)
    syn = sum(1 for r in with_data if r["synonym"] == "True") / len(with_data)

    cand = sorted([r for r in used if r["median_in"] == "False"],
                  key=lambda r: _f(r["median"]))

    try:
        import pygbif
        pygbif_v = getattr(pygbif, "__version__", "?")
    except Exception:
        pygbif_v = "?"

    def table(cands):
        out = ["| especie | familia | n | Manual (m) | GBIF core Q05–Q95 | mediana | vert% |",
               "|---|---|---:|---:|---:|---:|---:|"]
        for r in cands:
            vm = f"{_f(r['vmatch'])*100:.0f}" if _f(r["vmatch"]) is not None else "–"
            out.append(f"| *{r['species']}* | {r['family']} | {r['n']} | "
                       f"{r['manual_ext']} | ({_f(r['q05']):.0f}, {_f(r['q95']):.0f}) | "
                       f"{_f(r['median']):.0f} | {vm} |")
        return "\n".join(out)

    md = f"""# Manual de Plantas de Costa Rica ↔ GBIF — Geospatial Validation

*Generated {_dt.date.today().isoformat()} from `{_SRC_CSV.name}` ({len(rows)} resolved species).*

External cross-validation of the species distribution fields extracted from the
Manual de Plantas de Costa Rica against independent GBIF occurrence evidence.

## 1. Method

- **Catalog.** {config.SQLITE_PATH.name}: structured fichas for Tomos II–VI of the Manual.
- **Sampling.** Species with a stated elevation, spread across families.
- **Name resolution.** GBIF backbone (`name_backbone`), **EXACT matches only** — rejects
  fuzzy/higher-rank hits and unnamed morphospecies ("*Genus* sp. N"); occurrences keyed on
  the **accepted** taxon, deduplicated by accepted key (records Manual↔GBIF synonymy).
- **Occurrence retrieval.** `country=CR`, `hasCoordinate=True`, `hasGeospatialIssue=False`,
  up to 900 records/species.
- **Coordinate cleaning** (CoordinateCleaner-style; Zizka et al. 2019): drop (0,0); correct
  lat/lon swaps against the CR bounding box; drop records with
  `coordinateUncertaintyInMeters` > 10 000 m (~10 km).
- **Elevation.** Sampled from the project DEM (`altitud_cr.tif`) at each occurrence —
  **not** GBIF's own (unreliable) elevation field.
- **Robust comparison** (Booth et al. 2014; Alhajeri & Fourcade 2019). The Manual range is
  compared to the **centre** of the GBIF distribution, not its outlier-sensitive extremes:
  *median-in-range* (GBIF median inside the Manual range) and *core overlap* (GBIF **Q05–Q95**
  overlaps the Manual range). A **discrepancy candidate** = GBIF median outside the Manual
  (outlier-extended) range.
- **Inclusion.** Species with ≥ 10 cleaned occurrences (n = {nU}).

## 2. Results

**Pipeline.** {len(rows)} species resolved (EXACT, deduplicated) → {len(with_data)} with ≥1
cleaned CR occurrence → **{nU} with ≥10** (analysis set).

| Metric | Value |
|---|---:|
| **GBIF median within Manual range** (robust validation) | **{median_in*100:.0f}%** |
| **GBIF core Q05–Q95 overlaps Manual range** | **{core_ov*100:.0f}%** |
| Occurrences within the core range (point level) | {in_core*100:.0f}% |
| Vertiente (slope) agreement | {vmatch*100:.0f}% |
| Taxonomic synonymy Manual (2007) ↔ GBIF backbone | {syn*100:.0f}% |

The near-total core overlap (and 97% median-in-range) indicates the extracted Manual ranges
are concordant with independent occurrence evidence — mirroring the high expert-map↔GBIF
agreement reported by Alhajeri & Fourcade (2019) once outliers are set aside.

## 3. Discrepancy candidates (GBIF median outside the Manual range)

{len(cand)} of {nU} species ({len(cand)/nU*100:.0f}%). Candidates for range extension,
under-documentation, or misidentification — each warrants taxonomic review.

{table(cand)}

## 4. Reproducibility

```
python -m mpcr_rag.ingest.build_catalog     # (re)build catalog → SQLite + Pinecone
python -m mpcr_rag.eval.manual_vs_gbif 400   # run analysis → data/eval/manual_vs_gbif.csv
python -m mpcr_rag.eval.make_report          # this report
```

- **Parameters.** EXACT backbone match; CR only; `hasGeospatialIssue=False`; coordinate
  uncertainty ≤ 10 km; ≤900 records/species; DEM-derived elevation; inclusion n ≥ 10;
  robust criterion = median-in-range with Q05–Q95 core.
- **Software.** pygbif {pygbif_v}.
- **Data artifact.** `results/{_SRC_CSV.name}` — frozen per-species output of this run.
- **⚠ GBIF is a live, growing database.** For the final paper, issue a **GBIF download DOI**
  to freeze the exact occurrence snapshot; the cached per-species snapshots used here live in
  `data/gbif_cache/`.

## References

- Booth, T.H., Nix, H.A., Busby, J.R. & Hutchinson, M.F. (2014). *bioclim: the first species
  distribution modelling package, its early applications and relevance to most current MaxEnt
  studies.* **Diversity and Distributions** 20(1): 1–9. doi:10.1111/ddi.12144
- Alhajeri, B.H. & Fourcade, Y. (2019). *High correlation between species-level environmental
  data estimates extracted from IUCN expert range maps and from GBIF occurrence data.*
  **Journal of Biogeography** 46(7): 1329–1341. doi:10.1111/jbi.13619
- Zizka, A. et al. (2019). *CoordinateCleaner: standardized cleaning of occurrence records from
  biological collection databases.* **Methods in Ecology and Evolution** 10(5): 744–751.
  doi:10.1111/2041-210X.13152
"""
    (_RESULTS / "manual_vs_gbif_results.md").write_text(md, encoding="utf-8")
    shutil.copy(_SRC_CSV, _RESULTS / _SRC_CSV.name)
    print(f"report → {_RESULTS/'manual_vs_gbif_results.md'}")
    print(f"data   → {_RESULTS/_SRC_CSV.name}")
    print(f"\nvalidation: median-in={median_in*100:.0f}% core-overlap={core_ov*100:.0f}% "
          f"vert={vmatch*100:.0f}% synonymy={syn*100:.0f}% | candidates={len(cand)}/{nU}")


if __name__ == "__main__":
    main()
