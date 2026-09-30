# MPCR-RAG

Geospatial RAG over the *Manual de Plantas de Costa Rica*. A subproject of
**CR-BioLM** — see [PLAN.md](PLAN.md) for scope, architecture, and milestones.

It segments OCR'd Manual PDFs into per-species **fichas**, extracts structured
geospatial fields (reusing CR-BioLM's `utils/distribution_map/` pipeline), indexes
them in **Pinecone**, and answers geospatial questions with a **map + grounded text**
answer — e.g. *"arbustos que crecen entre 150 y 300 m"*.

## Setup

```bash
pip install -r requirements.txt
# add to ../.env:  PINECONE_API_KEY=...
```

## Pipeline

```
ingest/ficha_segmenter.py   PDF            → RawFicha   (layout-block segmentation)
ingest/field_extractor.py   RawFicha       → Ficha      (geo_parser + regex)
ingest/llm_enrich.py        Ficha          → +enrichment (cached LLM pass)
ingest/build_index.py       Ficha          → Pinecone + SQLite
query/retriever.py          name | NL Q    → Ficha(s)
query/answer.py             NL question    → map + grounded text
```

## Run the segmentation spike (Milestone 1)

```bash
python -m mpcr_rag.ingest.ficha_segmenter   # segments the first PDF in config.CORPUS
```

Corpus is a manifest in [config.py](config.py) — start with one PDF, append to expand.
