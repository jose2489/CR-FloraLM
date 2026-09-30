"""Full-catalog ingest: segment every CORPUS PDF → SQLite + Pinecone.

Run:  python -m mpcr_rag.ingest.build_catalog
"""
from __future__ import annotations

import os
import time
from collections import Counter

from .. import config
from ..ingest.field_extractor import extract_corpus_pdf
from ..store import local_store, pinecone_client as pc


def main() -> None:
    t0 = time.time()
    fichas = []
    for e in config.CORPUS:
        fs = extract_corpus_pdf(e)
        fichas.extend(fs)
        print(f"  {e['family']:28} {len(fs):4}  ({e['path'].name[:34]})", flush=True)
    print(f"\nextracted {len(fichas)} fichas in {time.time()-t0:.0f}s\n", flush=True)

    # de-dup by species (a few species can recur across files); keep richest
    by_id: dict[str, object] = {}
    for f in fichas:
        cur = by_id.get(f.vector_id)
        if cur is None or (f.distribution_paragraph and not cur.distribution_paragraph):
            by_id[f.vector_id] = f
    fichas = list(by_id.values())
    print(f"unique species: {len(fichas)}", flush=True)

    # SQLite (fresh)
    if os.path.exists(config.SQLITE_PATH):
        os.remove(config.SQLITE_PATH)
    conn = local_store.connect(config.SQLITE_PATH)
    n = local_store.upsert(conn, fichas)
    print(f"SQLite: {n} fichas → {config.SQLITE_PATH}", flush=True)

    # Pinecone (clean stale namespaces, then upsert)
    idx = pc.ensure_index()
    for ns in ("lauraceae", "mpcr_v6"):
        try:
            idx.delete(delete_all=True, namespace=ns)
        except Exception:
            pass
    m = pc.upsert_fichas(fichas, index=idx)
    print(f"Pinecone: {m} vectors → namespace '{pc._NAMESPACE}'", flush=True)

    print(f"\nper-volume:", flush=True)
    for v, c in sorted(Counter(f.volume for f in fichas).items()):
        print(f"  Tomo {v:4} {c}", flush=True)
    print(f"\nDONE in {time.time()-t0:.0f}s — {len(fichas)} species", flush=True)


if __name__ == "__main__":
    main()
