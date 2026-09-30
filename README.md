# CR-FloraLM

*Grounding the Flora*: verifiable geospatial question answering over the **Manual de
Plantas de Costa Rica**.

Companion code for the IEEE BIP 2026 paper *"Grounding the Flora: Verifiable Geospatial
Question Answering over Costa Rica's Plants."* CR-FloraLM is the flora-focused component
of the CR-BioLM project.

Large language models answer biodiversity questions fluently and are often wrong about
regional species, with no way to check them. CR-FloraLM converts the Manual de Plantas
de Costa Rica (Volumes II–VI: 5,791 species, 189 families) into a structured, queryable
catalog, answers natural-language geospatial questions with text grounded in the source
and cited to volume and page, and renders GBIF occurrence maps filtered by the same
constraints. Every claim in an answer can be traced back to a page of the Manual.

## What it does

Ask in Spanish; get a grounded answer, source citations, and a map.

```bash
python -m mpcr_rag.query.answer "arbustos endémicos de bosque nuboso sobre 2000 m en Talamanca"
```

The question is parsed into a metadata filter (`habit=arbusto`, `forest_type=nuboso`,
`elev_lo=2000`, `region=Cordillera de Talamanca`, `endemic=true`), executed over the
catalog, and the matching entries are passed to a composer that may use only those
entries. Three question types are supported: species lookup, combinatorial habitat
queries, and superlative queries ("the tree reaching the highest altitude in ...").

## Results reported in the paper

| Evaluation | Result |
| --- | --- |
| Extracted ranges vs. GBIF occurrences (N=268) | 97% agree at the median; core IoU 0.72 |
| Grounding: same model, with vs. without the retrieved entry (N=500) | elevation IoU 34% → 89%; slope 47% → 95% |
| Endemic species, the long tail (N=89) | elevation IoU 24% → 91% |
| Constraint parsing, held-out queries (N=30) | 29/30 filters exact; 269/270 fields |
| Retrieval vs. reference answer set (N=30) | recall 1.00; mean precision 0.97 |
| Extraction textual support (all 5,791 entries) | elevation 5,759/5,760; slope 5,747/5,747 |

Per-species results for all of these are committed under `mpcr_rag/eval/results/`.

## Layout

| Path | Contents |
| --- | --- |
| `mpcr_rag/ingest/` | PDF segmentation and structured field extraction |
| `mpcr_rag/query/` | Intent parsing, retrieval, answer composition, map rendering |
| `mpcr_rag/store/` | SQLite hydration store and Pinecone index client |
| `mpcr_rag/eval/` | Every evaluation reported in the paper |
| `utils/distribution_map/` | Deterministic geo-parser, gazetteer and map renderer |
| `data/` | The catalog build the paper reports |

## The catalog

`data/fichas_structured_bip2026.sqlite` is the build the paper reports: 5,791 species,
189 families, Volumes II–VI. Later builds in the parent project are larger and will
**not** reproduce the published figures.

It ships as **structured fields only** — elevation bounds, slope, botanical regions,
forest types, growth form, phenology, endemism, and the volume and page of every entry.
The verbatim distribution paragraphs are **not** included: that text is copyrighted by
Missouri Botanical Garden Press and is not ours to redistribute. Facts about where a
species grows are freely usable; the Manual's prose is not.

## Reproducing the paper

```bash
pip install -r requirements.txt
cp .env.example .env          # OPENROUTER_API_KEY, PINECONE_API_KEY
DB=data/fichas_structured_bip2026.sqlite
```

**Runs from this repository as cloned:**

```bash
python -m mpcr_rag.eval.range_width                  # Section V, agreement vs. range width
python -m mpcr_rag.eval.retrieval_eval --db $DB      # Section IV-F, 30 held-out queries
```

**Needs the geospatial layers** — occurrence altitudes are sampled from the digital
elevation model rather than taken from GBIF's own elevation field, and each occurrence
is spatially joined against the botanical-region polygons to determine its region and
slope:

```bash
python -m mpcr_rag.eval.manual_vs_gbif               # Table II
```

**Needs a catalog rebuilt from the Manual PDFs**, because these read the source
paragraph:

```bash
python -m mpcr_rag.eval.extraction_support --db DB_WITH_TEXT   # Section IV-A
python -m mpcr_rag.eval.rag_vs_baseline 500                    # Table III
python -m mpcr_rag.eval.bertscore 150                          # Table III
```

Committed results cover all six, so every published figure can be checked per species
even where the inputs cannot be redistributed. One caveat: `bertscore.csv` retains the
model's generated answers but not the Manual paragraphs they were scored against, so
BERTScore can be inspected but not recomputed without a text-carrying catalog.

## Data not included

Most of what is missing can be obtained directly, without contacting anyone.

**Freely available:**

- **Digital elevation model.** SRTM, public domain (NASA / USGS).
- **Protected areas.** Costa Rican national geographic information system (SNIT /
  SINAC), public geoportal.
- **GBIF occurrences.** The frozen snapshot used for validation is citable at
  <https://doi.org/10.15468/dl.8yhee8>; occurrences are otherwise fetched on demand.

**Obtainable from the publisher:**

- **The Manual de Plantas de Costa Rica.** Published by Missouri Botanical Garden Press.
  With the volumes in hand, `mpcr_rag/ingest/` rebuilds the full catalog, distribution
  paragraphs included, which is what the three text-dependent evaluations need.

**Available on request:**

- **Botanical-region polygons.** This is the one input that cannot be sourced
  elsewhere. It is our digitization of the phytogeographic map of Costa Rica drawn by
  **Marco V. Castro** for the Manual: the delineation of the regions is his work, ours
  is only its reproduction in vector form. Because the underlying map is not ours to
  redistribute, the layer is not published here. Open an issue or contact the authors
  and we will share it for research use, subject to the rights of the original map. We
  intend to publish it openly if permission to do so can be arranged.

Without the region polygons, the structured extraction, retrieval and parsing
evaluations still run in full; Table II and the map figures do not.

## Relationship to CR-BioLM

CR-FloraLM is extracted from the CR-BioLM research repository at the tag
`bip-2026-submission`, which is the state of the code the paper describes. Work in the
parent project that postdates the paper — an alternative local vector backend, an MCP
server, and a broader evidence layer — is deliberately excluded, so that this repository
corresponds to the published results rather than to current work in progress.

## Citation

> J. A. Araya C., M. A. Mora C., A. Estrada Chavarría and N. Zamora, "Grounding the
> Flora: Verifiable Geospatial Question Answering over Costa Rica's Plants," in *Proc.
> 8th IEEE International Conference on BioInspired Processing (BIP)*, Guápiles, Costa
> Rica, Nov. 2026.

```bibtex
@inproceedings{araya2026groundingflora,
  author    = {Araya C., Jose Arnaldo and Mora C., Maria Auxiliadora and
               Estrada Chavarr{\'i}a, Armando and Zamora, Nelson},
  title     = {Grounding the Flora: Verifiable Geospatial Question Answering
               over {Costa} {Rica}'s Plants},
  booktitle = {Proc. 8th IEEE International Conference on BioInspired Processing (BIP)},
  address   = {Gu{\'a}piles, Costa Rica},
  month     = nov,
  year      = {2026}
}
```

## License

Code is released under the [MIT License](LICENSE).

That covers the software only. The Manual de Plantas de Costa Rica remains copyrighted
by Missouri Botanical Garden Press; the botanical-region map is the work of Marco V.
Castro; and the protected-area layers, elevation model and GBIF records remain under
their own terms. None of those are redistributed here. The catalog in `data/` holds
factual attributes plus the volume and page of each entry, so any value can be traced
back to its source.
