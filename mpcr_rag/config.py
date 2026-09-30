"""Configuration for MPCR-RAG: corpus manifest, models, paths.

Expand the corpus by appending entries to ``CORPUS`` — nothing else changes.
Each volume should be validated (Milestone 1-style spike) before it is added.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# --- repo / data roots ------------------------------------------------------
RAG_ROOT = Path(__file__).resolve().parent
DATA_DIR = RAG_ROOT / "data"
SQLITE_PATH = DATA_DIR / "fichas.sqlite"
FICHAS_JSON_DIR = DATA_DIR / "fichas_json"

MANUAL_ROOT = Path(
    r"C:\Users\Jose\Documents\Tesis\raw_data\Manual de Especies\Nelson"
    r"\wetransfer_manual-plantas-cr_2026-05-29_1701\Manual Plantas de Costa Rica"
)

# --- corpus manifest (auto-discovered) --------------------------------------
# Scan the validated-format volumes, skipping non-content PDFs (front matter,
# indices, identification keys). VII/VIII are excluded for now — different OCR/
# layout era (2014 MBOT/InDesign) that needs separate tuning.
_VOL_DIRS = {
    "MPCRv2 PDFs": "II", "MPCRv3 PDFs": "III",
    "Vol IV": "IV", "Vol V": "V", "Vol VI": "VI",
}
_SKIP = re.compile(
    r"\bFM\b|ix_xviii|vii_xvi|index|indices|clave|gimno|\.ps1|z\dmpcr", re.I
)


# Vol VI continuation files use abbreviated prefixes → map back to the real family.
_FAMILY_FIX = {
    "LauraPersea": "Lauraceae", "MalpStigmaphyllon": "Malpighiaceae",
    "MalvaModiola": "Malvaceae", "MelaTococa": "Melastomataceae",
    "MelastoMiconia": "Melastomataceae", "MelastomHenriettella": "Melastomataceae",
}


def _family_from_name(name: str) -> str:
    stem = re.sub(r"^\d+\s*", "", name.rsplit(".pdf", 1)[0])   # strip leading "01 "
    m = re.match(r"([A-Za-zé_]+)", stem)
    fam = m.group(1) if m else ""
    if fam.upper().startswith("MPCR"):
        return ""
    return _FAMILY_FIX.get(fam, fam)


def _discover_corpus() -> list[dict]:
    out: list[dict] = []
    for sub, vol in _VOL_DIRS.items():
        folder = MANUAL_ROOT / sub
        if not folder.is_dir():
            continue
        for p in sorted(folder.glob("*.pdf")):
            if _SKIP.search(p.name):
                continue
            out.append({"path": p, "volume": vol,
                        "family": _family_from_name(p.name) or f"Vol {vol}"})
    return out


CORPUS: list[dict] = _discover_corpus()

# --- embeddings / vector store ---------------------------------------------
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
PINECONE_INDEX = "mpcr-fichas"
EMBED_MODEL = "multilingual-e5-large"   # Pinecone hosted inference
EMBED_DIM = 1024                        # e5-large; pin in methods section

# --- LLM enrichment (reuses CR-BioLM OpenRouter setup) ----------------------
ENRICH_MODEL = os.environ.get("MPCR_ENRICH_MODEL", "openai/gpt-4o-mini")

DATA_DIR.mkdir(exist_ok=True)
FICHAS_JSON_DIR.mkdir(exist_ok=True)
