"""SQLite hydration store for Ficha records.

Pinecone holds vectors + a small filterable metadata subset; this store holds the
full Ficha (serialized) keyed by the same ``vector_id``, so a retrieval hit can be
hydrated into a complete, citable record. Filterable columns are also broken out so
Pattern-B logic (e.g. "arbustos entre 150 y 300 m") can be prototyped offline here,
before the same filters are expressed as Pinecone metadata queries.

Run as a module to (re)build the store from the corpus and demo a query:
    python -m mpcr_rag.store.local_store
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..schema import Ficha

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fichas (
    vector_id  TEXT PRIMARY KEY,
    species    TEXT,
    genus      TEXT,
    family     TEXT,
    volume     TEXT,
    pages      TEXT,
    elev_min   INTEGER,
    elev_max   INTEGER,
    habits     TEXT,   -- json list
    endemic    INTEGER,
    ficha_json TEXT,   -- full Ficha
    full_text  TEXT
);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def upsert(conn: sqlite3.Connection, fichas: list[Ficha]) -> int:
    rows = [
        (
            f.vector_id, f.species, f.genus, f.family, f.volume, f.pages,
            f.elev_min, f.elev_max, json.dumps(f.habits, ensure_ascii=False),
            int(f.endemic_cr), f.to_json(), f.full_text,
        )
        for f in fichas
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO fichas "
        "(vector_id, species, genus, family, volume, pages, elev_min, elev_max, "
        " habits, endemic, ficha_json, full_text) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return len(rows)


def get(conn: sqlite3.Connection, vector_id: str) -> Ficha | None:
    r = conn.execute(
        "SELECT ficha_json FROM fichas WHERE vector_id = ?", (vector_id,)
    ).fetchone()
    return Ficha.from_json(r["ficha_json"]) if r else None


def hydrate(conn: sqlite3.Connection, vector_ids: list[str]) -> list[Ficha]:
    """Fetch full Fichas for a list of vector ids (Pinecone → full record)."""
    out = []
    for vid in vector_ids:
        f = get(conn, vid)
        if f:
            out.append(f)
    return out


def filter_fichas(
    conn: sqlite3.Connection,
    *,
    habit: str | None = None,
    elev_lo: int | None = None,
    elev_hi: int | None = None,
    endemic: bool | None = None,
) -> list[Ficha]:
    """Offline analogue of a Pinecone metadata filter.

    Elevation uses range *overlap*: a species [emin,emax] matches a query window
    [elev_lo,elev_hi] when emin <= elev_hi AND emax >= elev_lo.
    """
    sql = "SELECT ficha_json FROM fichas WHERE 1=1"
    args: list = []
    if habit is not None:
        sql += " AND habits LIKE ?"
        args.append(f'%"{habit}"%')
    if elev_hi is not None:
        sql += " AND elev_min IS NOT NULL AND elev_min <= ?"
        args.append(elev_hi)
    if elev_lo is not None:
        sql += " AND elev_max IS NOT NULL AND elev_max >= ?"
        args.append(elev_lo)
    if endemic is not None:
        sql += " AND endemic = ?"
        args.append(int(endemic))
    return [Ficha.from_json(r["ficha_json"]) for r in conn.execute(sql, args)]


def build_from_corpus(db_path: Path | None = None) -> int:
    """Extract all corpus PDFs and (re)persist them to the SQLite store."""
    from .. import config
    from ..ingest.field_extractor import extract_corpus_pdf

    db_path = db_path or config.SQLITE_PATH
    fichas: list[Ficha] = []
    for entry in config.CORPUS:
        fichas.extend(extract_corpus_pdf(entry))
    conn = connect(db_path)
    n = upsert(conn, fichas)
    conn.close()
    return n


if __name__ == "__main__":
    from .. import config

    n = build_from_corpus()
    print(f"persisted {n} fichas → {config.SQLITE_PATH}")

    conn = connect(config.SQLITE_PATH)
    # Demo Pattern B (offline): "arbustos que crecen entre 150 y 300 m"
    hits = filter_fichas(conn, habit="arbusto", elev_lo=150, elev_hi=300)
    print(f"\nPattern B demo — arbustos entre 150 y 300 m: {len(hits)} matches")
    for f in hits:
        print(f"  {f.species:32} [{f.elev_min}–{f.elev_max} m] {f.habits} "
              f"{'ENDÉMICA' if f.endemic_cr else ''}")
    conn.close()
