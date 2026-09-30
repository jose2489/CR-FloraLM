# mpcr_rag

The CR-FloraLM pipeline package. See the [repository README](../README.md) for what the
system does, how to reproduce the paper's results, and which data are required.

| Module | Role |
| --- | --- |
| `ingest/` | Segments Manual PDFs into per-species entries; extracts structured geospatial fields |
| `query/` | Intent parsing, retrieval, grounded answer composition, map rendering |
| `store/` | SQLite hydration store and Pinecone index client |
| `eval/` | Every evaluation reported in the paper, with committed results |

```
ingest/ficha_segmenter.py   PDF          -> RawFicha   (layout-block segmentation)
ingest/field_extractor.py   RawFicha     -> Ficha      (deterministic geo-parser)
ingest/build_catalog.py     Ficha        -> SQLite + Pinecone
query/retriever.py          name | NL Q  -> Ficha(s)
query/answer.py             NL question  -> grounded text + map
```

The deterministic geo-parser, gazetteer and map renderer that these build on live in
[`utils/distribution_map/`](../utils/distribution_map/).
