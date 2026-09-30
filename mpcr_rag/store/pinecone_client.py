"""Pinecone wrapper using integrated (hosted) inference.

The index is created *for a model* (``multilingual-e5-large``), so Pinecone embeds
records on upsert and queries on search server-side — no separate embedding call,
and the e5 query/passage prefixes are applied automatically. The embedded text is
the species' distribution paragraph; a small, filterable metadata subset rides along.

Pinecone metadata supports str / number / bool / list[str] only, so int lists
(flowering_months) are stringified.
"""
from __future__ import annotations

import time

from pinecone import Pinecone

from .. import config
from ..schema import Ficha

_TEXT_FIELD = "text"           # must match the index field_map
_NAMESPACE = "mpcr"            # full multi-volume catalog


def client() -> Pinecone:
    if not config.PINECONE_API_KEY:
        raise RuntimeError("PINECONE_API_KEY missing (.env)")
    return Pinecone(api_key=config.PINECONE_API_KEY)


def ensure_index(pc: Pinecone | None = None) -> "object":
    """Create the model-backed index if absent; return a handle once ready."""
    pc = pc or client()
    names = [i.name for i in pc.list_indexes()]
    if config.PINECONE_INDEX not in names:
        pc.create_index_for_model(
            name=config.PINECONE_INDEX,
            cloud="aws",
            region="us-east-1",
            embed={
                "model": config.EMBED_MODEL,
                "field_map": {"text": _TEXT_FIELD},
            },
        )
    # Wait until ready.
    for _ in range(60):
        desc = pc.describe_index(config.PINECONE_INDEX)
        status = getattr(desc, "status", None)
        ready = status.get("ready") if isinstance(status, dict) else getattr(status, "ready", False)
        if ready:
            break
        time.sleep(2)
    return pc.Index(config.PINECONE_INDEX)


def _record(f: Ficha) -> dict:
    """Build an upsert record: id + text-to-embed + filterable metadata."""
    return {
        "_id": f.vector_id,
        _TEXT_FIELD: f.distribution_paragraph or f.species,
        "species": f.species,
        "genus": f.genus,
        "family": f.family,
        "volume": f.volume,
        "pages": f.pages,
        "elev_min": f.elev_min if f.elev_min is not None else -1,
        "elev_max": f.elev_max if f.elev_max is not None else -1,
        # outlier-extended bounds (occasional records), for "possible" inclusion
        "elev_min_eff": (f.elev_outlier_min if f.elev_outlier_min is not None
                         else f.elev_min) if f.elev_min is not None else -1,
        "elev_max_eff": (f.elev_outlier_max if f.elev_outlier_max is not None
                         else f.elev_max) if f.elev_max is not None else -1,
        "habits": f.habits or [],
        "vertientes": f.vertientes or [],
        "regions": f.regions or [],
        "forest_types": f.forest_types or [],
        "endemic": f.endemic_cr,
        "flowering_months": [str(m) for m in f.flowering_months],
    }


def upsert_fichas(fichas: list[Ficha], index=None, batch: int = 90) -> int:
    index = index or ensure_index()
    records = [_record(f) for f in fichas]
    for i in range(0, len(records), batch):
        index.upsert_records(namespace=_NAMESPACE, records=records[i:i + batch])
    return len(records)


def search(query_text: str, *, top_k: int = 10, flt: dict | None = None,
           index=None) -> list[dict]:
    """Semantic search (optionally metadata-filtered). Returns hit dicts with
    _id, _score, and the stored fields."""
    index = index or ensure_index()
    res = index.search(
        namespace=_NAMESPACE,
        inputs={"text": query_text},
        top_k=top_k,
        filter=flt or None,
    )
    hits = []
    for row in res["result"]["hits"]:
        hits.append({"id": row.id, "score": row.score, **dict(row.fields)})
    return hits


if __name__ == "__main__":
    from ..ingest.field_extractor import extract_corpus_pdf

    fichas = []
    for entry in config.CORPUS:
        fichas.extend(extract_corpus_pdf(entry))

    print(f"ensuring index '{config.PINECONE_INDEX}' ({config.EMBED_MODEL}) …")
    idx = ensure_index()
    n = upsert_fichas(fichas, index=idx)
    print(f"upserted {n} records; waiting for indexing …")
    time.sleep(10)

    print("\n--- semantic search: 'bosque nuboso de altura en Talamanca' ---")
    for h in search("bosque nuboso de altura en la Cordillera de Talamanca",
                    top_k=5, index=idx):
        print(f"  {h['score']:.3f}  {h['species']:30} [{h.get('elev_min')}-{h.get('elev_max')} m]")
