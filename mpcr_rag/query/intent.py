"""Natural-language → structured query intent.

Turns a free Spanish question ("arbustos de bosque nuboso sobre 2000 m en Talamanca")
into the structured constraints that ``retriever.pattern_b`` consumes. An LLM maps
the phrasing onto the catalog's CONTROLLED VOCABULARY (the distinct habits, forest
types, vertientes, regions, families actually present), so the resulting Pinecone
metadata filter uses exact stored values. Whatever isn't a structured field becomes
``semantic_text`` for the vector search.
"""
from __future__ import annotations

import json
import os

import requests

from .. import config
from ..store import local_store
from ..schema import Ficha

_HABITS = ["árbol", "arbusto", "hierba", "bejuco", "epífita", "hemiepífita",
           "palma", "terrestre", "acuática", "sufrútice", "parásita"]
_MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
           "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
           "noviembre": 11, "diciembre": 12}

# Selection criteria available for "superlative" questions (pick ONE species from
# the filtered set). elev_max/elev_min/n_regions are deterministic Ficha fields —
# fully grounded in the Manual. gbif_count is an explicit PROXY (collection effort,
# not abundance) for "más común/abundante", since the Manual has no abundance field.
_SELECTOR_CRITERIA = {"elev_max", "elev_min", "n_regions", "gbif_count"}


def load_vocab(conn=None) -> dict:
    """Distinct controlled values present in the catalog."""
    conn = conn or local_store.connect(config.SQLITE_PATH)
    rows = [Ficha.from_json(r["ficha_json"])
            for r in conn.execute("SELECT ficha_json FROM fichas")]
    forests, regions, families = set(), set(), set()
    for f in rows:
        forests.update(f.forest_types)
        regions.update(f.regions)
        families.add(f.family)
    return {
        "habits": _HABITS,
        "forest_types": sorted(forests),
        "vertientes": ["Caribe", "Pacífico"],
        "regions": sorted(regions),
        "families": sorted(families),
    }


_SYSTEM = """Eres un parser que convierte preguntas en español sobre plantas de Costa
Rica en un filtro estructurado JSON. Usa ÚNICAMENTE valores de las listas permitidas
(copia exactamente; si no aplica, null). Reglas de elevación (metros):
- "entre X y Y" -> elev_lo=X, elev_hi=Y
- "sobre/arriba de/más de/encima de X" -> elev_lo=X, elev_hi=null
- "bajo/debajo de/menos de X" -> elev_lo=null, elev_hi=X
- "a X m" o "alrededor de X" -> elev_lo=X-150, elev_hi=X+150
endemic=true si la pregunta dice "endémica(s)/endémico(s)/solo de Costa Rica/exclusivas de CR".
flowering_month = número de mes si dice "florece(n) en <mes>" (enero=1 … diciembre=12).
vertiente: "del Caribe/caribeña/atlántica" -> Caribe; "del Pacífico/pacífica" -> Pacífico.

intent_type="superlative" SOLO cuando la pregunta pide UNA ÚNICA especie que cumple una
condición extrema ("más común/abundante", "mayor/menor elevación", "distribución más
amplia/restringida", "la única que..."). En ese caso fija:
- selector_criterion: "elev_max" (crece a mayor altitud) | "elev_min" (menor altitud) |
  "n_regions" (aparece en más/menos regiones del Manual, proxy de amplitud de distribución) |
  "gbif_count" (más registros GBIF — el ÚNICO proxy disponible para "más común/abundante",
  porque el Manual no registra abundancia; NUNCA lo presentes como abundancia real).
- selector_direction: "max" si pide el extremo alto ("mayor", "más amplia", "más común"),
  "min" si pide el extremo bajo ("menor", "más restringida").
Si la pregunta pide una LISTA de especies (no una sola), intent_type="list" y
selector_criterion=null. Responde SOLO el JSON."""


def parse_intent(question: str, vocab: dict | None = None) -> dict:
    """LLM-map a question to {habit, elev_lo, elev_hi, vertiente, region,
    forest_type, family, flowering_month, endemic, semantic_text}."""
    vocab = vocab or load_vocab()
    schema = {
        "habit": f"uno de {vocab['habits']} o null",
        "forest_type": f"uno de {vocab['forest_types']} o null",
        "vertiente": "Caribe, Pacífico o null",
        "region": f"uno de {vocab['regions']} o null",
        "family": f"una de {vocab['families']} o null",
        "elev_lo": "int o null", "elev_hi": "int o null",
        "flowering_month": "1-12 o null", "endemic": "true/false/null",
        "intent_type": "'list' o 'superlative'",
        "selector_criterion": f"uno de {sorted(_SELECTOR_CRITERIA)} o null",
        "selector_direction": "'max' o 'min' o null",
        "semantic_text": "string",
    }
    prompt = (f"Listas permitidas y formato:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
              f"Pregunta: {question}")
    key = os.environ.get("OPENROUTER_API_KEY", "")
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": config.ENRICH_MODEL, "temperature": 0,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": _SYSTEM},
                           {"role": "user", "content": prompt}]},
        timeout=30,
    )
    data = json.loads(resp.json()["choices"][0]["message"]["content"])
    return _validate(data, vocab)


def _validate(d: dict, vocab: dict) -> dict:
    """Keep only values that exist in the controlled vocabulary."""
    def pick(key, allowed):
        v = d.get(key)
        return v if v in allowed else None

    out = {
        "habit": pick("habit", vocab["habits"]),
        "forest_type": pick("forest_type", vocab["forest_types"]),
        "vertiente": pick("vertiente", vocab["vertientes"]),
        "region": pick("region", vocab["regions"]),
        "family": pick("family", vocab["families"]),
        "elev_lo": d.get("elev_lo") if isinstance(d.get("elev_lo"), int) else None,
        "elev_hi": d.get("elev_hi") if isinstance(d.get("elev_hi"), int) else None,
        "flowering_month": d.get("flowering_month")
            if isinstance(d.get("flowering_month"), int) else None,
        "endemic": d.get("endemic") if isinstance(d.get("endemic"), bool) else None,
        "intent_type": "superlative" if d.get("intent_type") == "superlative" else "list",
        "selector_criterion": pick("selector_criterion", _SELECTOR_CRITERIA),
        "selector_direction": d.get("selector_direction") if d.get("selector_direction") in ("max", "min") else "max",
        "semantic_text": d.get("semantic_text") or "",
    }
    if out["intent_type"] != "superlative" or not out["selector_criterion"]:
        out["intent_type"] = "list"
        out["selector_criterion"] = None
        out["selector_direction"] = None
    return out


def ask(question: str, *, top_k: int = 15, conn=None, index=None):
    """End-to-end: NL question → parsed intent + ranked (Ficha, score) results."""
    from . import retriever as R
    from ..store import pinecone_client as pc

    conn = conn or local_store.connect(config.SQLITE_PATH)
    index = index or pc.ensure_index()
    intent = parse_intent(question)
    # Drop the intent-routing fields (handled by answer.py); keep only metadata filters.
    _routing = {"intent_type", "selector_criterion", "selector_direction", "semantic_text"}
    constraints = {k: v for k, v in intent.items()
                   if k not in _routing and v is not None}
    query_text = intent["semantic_text"] or question
    results = R.pattern_b(query_text, top_k=top_k, conn=conn, index=index, **constraints)
    return intent, results


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "arbustos endémicos de bosque nuboso sobre 2000 m en Talamanca"
    intent, results = ask(q)
    print(f"PREGUNTA: {q}\nINTENT: {json.dumps(intent, ensure_ascii=False)}\n")
    print(f"{len(results)} resultados:")
    for f, s in results[:12]:
        print(f"  rel={s:.3f}  {f.species:30} [{f.family}] [{f.elev_min}-{f.elev_max}m] {f.habits}")
