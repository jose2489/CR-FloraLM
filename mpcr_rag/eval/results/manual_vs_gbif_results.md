# Manual de Plantas de Costa Rica ↔ GBIF — Geospatial Validation

*Generated 2026-06-09 from `manual_vs_gbif.csv` (395 resolved species).*

External cross-validation of the species distribution fields extracted from the
Manual de Plantas de Costa Rica against independent GBIF occurrence evidence.

## 1. Method

- **Catalog.** fichas.sqlite: structured fichas for Tomos II–VI of the Manual.
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
- **Inclusion.** Species with ≥ 10 cleaned occurrences (n = 268).

## 2. Results

**Pipeline.** 395 species resolved (EXACT, deduplicated) → 375 with ≥1
cleaned CR occurrence → **268 with ≥10** (analysis set).

| Metric | Value |
|---|---:|
| **GBIF median within Manual range** (robust validation) | **97%** |
| **GBIF core Q05–Q95 overlaps Manual range** | **100%** |
| Occurrences within the core range (point level) | 81% |
| Vertiente (slope) agreement | 95% |
| Taxonomic synonymy Manual (2007) ↔ GBIF backbone | 14% |

The near-total core overlap (and 97% median-in-range) indicates the extracted Manual ranges
are concordant with independent occurrence evidence — mirroring the high expert-map↔GBIF
agreement reported by Alhajeri & Fourcade (2019) once outliers are set aside.

## 3. Discrepancy candidates (GBIF median outside the Manual range)

8 of 268 species (3%). Candidates for range extension,
under-documentation, or misidentification — each warrants taxonomic review.

| especie | familia | n | Manual (m) | GBIF core Q05–Q95 | mediana | vert% |
|---|---|---:|---:|---:|---:|---:|
| *Cenchrus multiflorus* | Pandanaceae_Poaceae | 11 | 800-800 | (2, 29) | 4 | 100 |
| *Pithecellobium johansenii* | Vol V | 12 | 50-100 | (14, 77) | 20 | 100 |
| *Calathea gloriana* | Lemnaceae_Musaceae | 10 | 100-150 | (38, 219) | 68 | 90 |
| *Wullschlaegelia calcarata* | Orchidaceae | 12 | 150-350 | (68, 397) | 122 | 100 |
| *Spirodela intermedia* | Lemnaceae_Musaceae | 10 | 0-50 | (11, 1559) | 301 | 100 |
| *Ilex guianensis* | Vol IV | 53 | 0-700 | (7, 1708) | 1151 | 100 |
| *Isochilus chiriquensis* | Orchidaceae | 10 | 1100-1450 | (797, 1802) | 1454 | 90 |
| *Topobea gerardoana* | Melastomataceae | 15 | 1900-2100 | (1719, 2338) | 2149 | 100 |

## 4. Reproducibility

```
python -m mpcr_rag.ingest.build_catalog     # (re)build catalog → SQLite + Pinecone
python -m mpcr_rag.eval.manual_vs_gbif 400   # run analysis → data/eval/manual_vs_gbif.csv
python -m mpcr_rag.eval.make_report          # this report
```

- **Parameters.** EXACT backbone match; CR only; `hasGeospatialIssue=False`; coordinate
  uncertainty ≤ 10 km; ≤900 records/species; DEM-derived elevation; inclusion n ≥ 10;
  robust criterion = median-in-range with Q05–Q95 core.
- **Software.** pygbif 0.6.6.
- **Data artifact.** `results/manual_vs_gbif.csv` — frozen per-species output of this run.
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
