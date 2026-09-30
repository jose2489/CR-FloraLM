# MPCR-RAG — Geospatial RAG over the *Manual de Plantas de Costa Rica*

**Paper target:** BIP event — **deadline July 2026**.
**Status:** scaffolding (started 2026-06-04).

A subproject of **CR-BioLM**. It reuses the existing map pipeline
(`utils/distribution_map/`) and adds one new capability: a Retrieval-Augmented
Generation layer over the OCR'd Manual de Plantas that dynamically fetches a
species' distribution description, renders the polished distribution map, and
**answers geospatial questions grounded in the source text** — benchmarked against
a bare-LLM baseline.

---

## 1. Scope

### In scope (this paper)
- **RAG ingestion** of a *validated subset* of Manual volumes into a Pinecone index.
- **Per-species fichas** with structured fields extracted at ingestion time.
- **Two query patterns**, served from the index + the existing renderer:
  - **A — Build the map:** species name → ficha → map.
  - **B — Answer a geospatial question:** NL question → metadata-filtered retrieval
    → **map + grounded text answer with page-level provenance**.
- **Evaluation** vs a bare-LLM baseline, ground-truthed on Armando's expert maps + GBIF.

### Out of scope (deferred to a later paper)
- xAI / explainability layers.
- Random-Forest SDM comparison.
- Full-corpus ingestion (all of Vol II–VIII) — start with the validated subset, design to scale.

### The contribution
A grounded, **citable** geospatial answer (map + text + Manual page) vs. a frontier
LLM's plausible-but-unsourced answer. Secondary result: accuracy of an LLM
structured-extraction pass that turns semi-structured flora prose into a queryable schema.

---

## 2. Architecture

```
Validated subset of Manual PDFs (high-quality OCR)
  │
  ├─[ingest/ficha_segmenter]  PDF → per-species RawFicha
  │       layout-block segmentation; anchors = binomial header + distribution paragraph
  │       (every other section is OPTIONAL — fichas are NOT uniform)
  │
  ├─[ingest/field_extractor]  RawFicha → Ficha
  │       distribution paragraph splits on its `m;` boundary into
  │       (habitat_raw, geographic_notes) → REUSES utils/distribution_map:
  │         _parse_elevation · _parse_forest_types · parse_distribution_block · build_ficha
  │       + deterministic regex: endemism, phenology (Fl./Fr.), global range, voucher
  │
  ├─[ingest/llm_enrich]       Ficha → +enrichment (cached LLM JSON pass)
  │       habit · common_names · uses · conservation note  (fields regex can't reliably get)
  │
  └─[ingest/build_index]
        • vector   = embedding(distribution_paragraph)   ← e5-large, Pinecone hosted
        • Pinecone metadata = filterable fields only (species, family, elev_min/max,
                              vertientes[], regions[], habit, endemic, flowering_months[])
        • local store (SQLite) = full Ficha JSON + full_text + pages   (hydration source)

Query
  ├─ A: species name → exact metadata match → Ficha → renderer.py → MAP
  └─ B: NL question → metadata filter + semantic rank → hydrate Fichas
         → renderer.py (MAP)  +  LLM compose grounded text w/ page citations

Eval  vs  bare-LLM baseline   (ground truth: Armando expert maps + GBIF occurrences)
```

---

## 3. Query patterns in detail

### Pattern A — species → map (keyed lookup, not semantic)
`"Aiouea obscura"` → `filter: species == "Aiouea obscura"` → hydrate ficha → `renderer.py`.

### Pattern B — geospatial natural-language question (the headline feature)
The metadata does the hard filtering; the embedding only ranks within survivors.

> **"Arbustos que crecen entre 150 y 300 m de altura"**
> → parse intent → `filter: habit == "arbusto" AND elev_min <= 300 AND elev_max >= 150`
> → semantic rank over distribution-paragraph vectors
> → **map** of the matching species + **grounded text** listing them, each with Manual page.

Other example questions the schema supports out of the box:
- *"¿Qué especies endémicas crecen sobre los 2000 m en la vertiente Caribe?"*
  `endemic == true AND elev_min >= 2000 AND vertientes contains "Caribe"`
- *"Árboles de la Cordillera de Talamanca que florecen en enero"*
  `habit == "árbol" AND regions contains "Cord. de Talamanca" AND flowering_months contains 1`

---

## 4. Chunking strategy — structure-aware, **no overlap** (a deliberate departure)

Generic RAG slices documents into fixed ~token windows with overlap. We do **not**:

- **One chunk = one species' distribution paragraph** — a natural, semantically complete
  document element with a hard boundary the segmenter already found. One vector per species.
- **No overlap.** Overlap exists in naive RAG to stop a relevant passage being split across
  an arbitrary window boundary. We segment on *real* ficha boundaries, so nothing bleeds
  across — overlap would only duplicate hits and mix two species' elevations.
- This **structure-aware chunking** is itself a methodological point: for flora text it
  strictly beats sliding windows (which would shred a ficha and conflate species).
- **Embedded text = the distribution paragraph only** (the geo-relevant unit). Enrichment
  fields remain queryable via metadata filter, so non-geo questions work without vector bloat.
  (A second vector over the full ficha can be added later if semantic search over
  common-names/uses is ever needed — not in v1.)

---

## 5. The `Ficha` schema

Identity + geospatial fields are **deterministic** (segmenter + `geo_parser`); the
enrichment block is **regex or LLM**. Every field is independently nullable — fichas are
not uniform, so no field's absence may break the parse.

```python
@dataclass
class Ficha:
    # identity ........................................ (segmenter)
    species: str            # accepted binomial
    authority: str
    genus: str
    family: str
    synonyms: list[str]
    volume: str
    pages: str              # provenance for citations

    # geospatial — DETERMINISTIC, the paper's core .... (geo_parser / parser)
    elev_min: int | None
    elev_max: int | None
    vertientes: list[str]
    regions: list[str]
    forest_types: list[str]
    distribution_paragraph: str   # embedded vector text

    # enrichment — regex / LLM, "available for answers"
    habit: str | None             # árbol / arbusto / hierba / epífita / bejuco
    common_names: list[str]
    endemic_cr: bool
    global_range: str | None      # e.g. "CR y O Pan."
    flowering_months: list[int]
    fruiting_months: list[int]
    uses: str | None

    full_text: str                # complete ficha, for provenance/hydration
```

**Storage split (avoid Pinecone's ~40 KB metadata cap):** filterable fields → Pinecone
metadata; full `Ficha` JSON + `full_text` → **SQLite** local store, hydrated by vector id.

---

## 6. Technology decisions (settled)

| Decision | Choice | Rationale |
|---|---|---|
| Corpus scope | Validated subset; **start with 1 PDF (Lauraceae)** | Lowest risk for July; design scales by appending to a manifest |
| Embeddings | **Pinecone hosted `multilingual-e5-large`** | Metadata does the discriminating; e5 handles Spanish; one vendor. Pin model+dim in methods |
| Vector store | **Pinecone** (free Starter tier, serverless) | Stated contribution; needs `PINECONE_API_KEY` in `.env`; hosted inference included (no separate embed key) |
| Local store / DB | **SQLite** | Single file, zero-config; hydration by vector id; offline re-runs without API; inspectable |
| Answer mode | **Map + grounded text** | Strongest contrast vs text-only baseline; provenance |
| Enrichment | **Hybrid** (geo_parser + cached LLM pass) | Soft fields need LLM; report extraction accuracy |
| Housing | Subproject in CR-BioLM | Reuse live pipeline, no data dup, liftable later |
| Chunking | Structure-aware, one vector/species, **no overlap** | Natural ficha boundaries; see §4 |

Swap paths: if eval shows retrieval misses → `text-embedding-3-large` (drop-in). If a
reviewer pushes on reproducibility → local FAISS/Chroma over the same vectors (zero key).

---

## 7. Repo layout (`mpcr_rag/`)

```
mpcr_rag/
  PLAN.md                 ← this file
  README.md               run instructions
  requirements.txt        pymupdf, pinecone, python-dotenv (no heavy ML deps)
  config.py               CORPUS manifest, index name, model names, paths
  schema.py               RawFicha + Ficha dataclasses
  ingest/
    ficha_segmenter.py    PDF → RawFicha   (layout-block segmentation)
    field_extractor.py    RawFicha → Ficha (reuses utils/distribution_map)
    llm_enrich.py         LLM structured pass (cached)
    build_index.py        Ficha → Pinecone + SQLite
  store/
    local_store.py        SQLite hydration store
    pinecone_client.py    index wrapper
  query/
    retriever.py          Pattern A + B retrieval
    answer.py             grounded answer + map render
  eval/
    questions.yaml        evaluation question set
    baseline.py           bare-LLM baseline
    harness.py            scoring vs Armando maps + GBIF
  tests/
  data/
    fichas.sqlite         local store
    fichas_json/          optional human-inspectable dumps
```

---

## 8. Milestones → July

| # | Milestone | Exit criterion | Target |
|---|---|---|---|
| 0 | Scaffold + PLAN | dirs, schema, config, requirements committed | wk of Jun 04 |
| 1 | **Segmentation spike** (Lauraceae, 1 PDF) | clean `(species, distribution_paragraph)` for ~all spp.; missing-field cases flagged, not crashed | wk of Jun 04 |
| 2 | Field extractor wired | `geo_parser` fields match hand-curated list on overlapping species (regression) | wk of Jun 09 |
| 3 | LLM enrichment + accuracy table | habit/common-names/etc. extracted; spot-checked accuracy logged | wk of Jun 16 |
| 4 | Subset ingested to Pinecone + SQLite | Pattern A & B return correct fichas on test queries | wk of Jun 16 |
| 5 | Grounded answer + map composition | end-to-end NL question → map + cited text | wk of Jun 23 |
| 6 | Eval harness + baseline + results | quantified delta vs bare-LLM on the question set | wk of Jun 23 |
| 7 | Write-up | draft submitted | early July |

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| **Ficha segmentation** across volume layouts (highest) | De-risk on one family first; anchor only on header + distribution paragraph; flag (don't crash on) missing sections |
| Non-uniform fichas (missing morphology/etc.) | Every field independently nullable; no section required |
| 2-column / interleaved OCR in some volumes | Block sort by (page, column, y); validate per volume before ingest |
| LLM enrichment flakiness | Non-critical path — ship without a field if unreliable; cache + spot-check |
| Hosted-embedding reproducibility | Pin model name + dimension in methods; local-store re-runs need no API |
| Pinecone metadata size cap | Filterable fields only in index; full ficha in SQLite |

---

## 10. Reuse map (from CR-BioLM, unchanged)

| From `utils/distribution_map/` | Used for |
|---|---|
| `geo_parser.parse_distribution_block` | vertiente + regions from `geographic_notes` |
| `parser._parse_elevation`, `_parse_forest_types` | elevation + forest from `habitat_raw` |
| `parser.build_ficha` | full structured resolution (regions, parks, elevation) |
| `gazetteer.py` + `entities.csv` + MOBOT gpkg | name resolution |
| `renderer.py` + shapefiles + DEM | the polished map (the answer artifact) |
