"""End-to-end answer layer — the system figure.

A natural-language question → (1) routed to species lookup or geospatial filter,
(2) a *grounded* text answer composed only from the retrieved Manual fichas, with
page citations, (3) a GBIF occurrence map of the matching species filtered by the
query constraints, and (4) the collection-bias disclaimer + 'insufficient evidence'
flags. Renders a Markdown report (map embedded) for presentation.
"""
from __future__ import annotations

import json
import os
import re
import textwrap
from concurrent.futures import ThreadPoolExecutor

import requests

from .. import config
from ..schema import Ficha
from ..store import local_store, pinecone_client as pc
from . import gbif_map
from . import retriever as R
from .intent import parse_intent

_ANSWERS = config.DATA_DIR / "answers"
_ANSWERS.mkdir(exist_ok=True)

_DISCLAIMER = (
    "*Los puntos son registros de GBIF y reflejan **esfuerzo de colecta**, no abundancia; "
    "la ausencia de puntos no implica ausencia de la especie. El rango de referencia "
    "proviene del Manual de Plantas de Costa Rica. Especies con <5 registros se marcan "
    "como evidencia insuficiente.*"
)


def _detect_species(question: str, conn) -> str | None:
    """If the question names a catalog species (binomial), return it."""
    for m in re.finditer(r"\b([A-Z][a-záéíóúñ]+)\s+([a-záéíóúñ]{3,})\b", question):
        cand = f"{m.group(1)} {m.group(2)}"
        if local_store.get(conn, cand.replace(" ", "_")):
            return cand
    return None


def _compose(question: str, results: list[tuple[Ficha, float]], *,
             selection_note: str | None = None) -> str:
    """LLM-compose a grounded answer using ONLY the retrieved fichas (with cites).

    ``selection_note``, when set, names the EXTERNAL criterion (not Manual text)
    that picked this single species out of a larger candidate set (superlative
    recipe) — the prompt forces the model to attribute the pick to that criterion
    instead of asserting it as a Manual fact.
    """
    ctx = "\n".join(
        f"- {f.species} (Tomo {f.volume}, p.{f.pages}): {f.distribution_paragraph}"
        for f, _ in results[:12])
    sys = ("Eres un botánico de Costa Rica. Responde la pregunta USANDO ÚNICAMENTE las "
           "fichas dadas; no agregues datos externos. Cita la especie y (Tomo, página) "
           "para cada afirmación. Sé conciso. Si no hay fichas, dilo.")
    user = f"Fichas:\n{ctx}\n\nPregunta: {question}"
    if selection_note:
        sys += (" Esta especie fue elegida entre varias candidatas usando un criterio "
                "EXTERNO al Manual (se indica abajo); menciónalo explícitamente como la "
                "razón de la elección — no lo presentes como un dato del texto del Manual.")
        user = f"Criterio de selección aplicado: {selection_note}\n\n{user}"
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY','')}",
                     "Content-Type": "application/json"},
            json={"model": config.ENRICH_MODEL, "temperature": 0,
                  "messages": [{"role": "system", "content": sys},
                               {"role": "user", "content": user}]},
            timeout=40)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"(síntesis no disponible: {e})"


_SELECTOR_LABELS = {
    "elev_max": "elevación máxima reportada en el Manual (m)",
    "elev_min": "elevación mínima reportada en el Manual (m)",
    "n_regions": "número de regiones botánicas donde el Manual reporta la especie",
    "gbif_count": "registros GBIF en Costa Rica (proxy de esfuerzo de colecta, NO de abundancia)",
}


def _select_superlative(candidates: list[Ficha], criterion: str, direction: str
                        ) -> tuple[Ficha | None, str]:
    """Deterministically pick ONE species from the full candidate set by `criterion`.

    elev_max/elev_min/n_regions are exact Ficha fields (fully grounded in the
    Manual); gbif_count is the only available proxy for "most common/abundant"
    (the Manual encodes no abundance field) and is always reported as a proxy.
    """
    if not candidates:
        return None, ""
    if criterion == "gbif_count":
        with ThreadPoolExecutor(max_workers=12) as ex:
            counts = list(ex.map(lambda f: gbif_map.count_only(f.species), candidates))
        scored = list(zip(candidates, counts))
    elif criterion == "n_regions":
        scored = [(f, len(f.regions)) for f in candidates]
    elif criterion in ("elev_max", "elev_min"):
        scored = [(f, getattr(f, criterion)) for f in candidates if getattr(f, criterion) is not None]
    else:
        return None, ""
    if not scored:
        return None, ""
    scored.sort(key=lambda t: t[1], reverse=(direction == "max"))
    winner, value = scored[0]
    return winner, (f"{_SELECTOR_LABELS[criterion]} = {value}  "
                     f"(entre {len(candidates)} especies candidatas que cumplen el filtro)")


_INTENT_KEYS = ("intent_type", "selector_criterion", "selector_direction", "semantic_text")


def answer(question: str, *, top_k: int = 12, conn=None, index=None) -> dict:
    """Routes the question to one of three fixed, citable recipes:

    A  (lookup)      — a named species  -> Manual-grounded map (single_species_map).
    B  (list)        — geospatial filter -> GBIF 'most likely' evidence map, multi-species.
    B->A (superlative) — geospatial filter, but the question asks for ONE species under
                          an extremal criterion -> exhaustive filter (no top_k/semantic
                          rank) + deterministic selection -> Manual-grounded map of the winner.

    This is a router + fixed dispatch table, not an open-ended agent: every recipe
    only calls the existing deterministic/citable building blocks below.
    """
    conn = conn or local_store.connect(config.SQLITE_PATH)
    index = index or pc.ensure_index()
    selector = None

    sp = _detect_species(question, conn)
    if sp:
        f = local_store.get(conn, sp.replace(" ", "_"))
        results, constraints, mode = [(f, 1.0)], {}, "A (especie)"
        map_path, n_pts = gbif_map.single_species_map(f)
    else:
        intent = parse_intent(question)
        constraints = {k: v for k, v in intent.items()
                       if k not in _INTENT_KEYS and v is not None}

        if intent["intent_type"] == "superlative":
            candidates = R.filter_all(conn=conn, **constraints)
            winner, selector = _select_superlative(
                candidates, intent["selector_criterion"], intent["selector_direction"])
            if winner is None:
                results, mode = [], "B→A (superlativo, sin resultados)"
                map_path, n_pts = gbif_map.most_likely_map([], query_text=question)
            else:
                results, mode = [(winner, 1.0)], "B→A (superlativo)"
                map_path, n_pts = gbif_map.single_species_map(winner)
        else:
            results = R.pattern_b(intent.get("semantic_text") or question,
                                  top_k=top_k, conn=conn, index=index, **constraints)
            mode = "B (geoespacial)"
            map_c = {k: constraints.get(k) for k in ("elev_lo", "elev_hi", "vertiente", "region")}
            map_path, n_pts = gbif_map.most_likely_map(results, query_text=question, **map_c)

    text = (_compose(question, results, selection_note=selector) if results
            else "No se encontraron especies que cumplan los criterios de la pregunta.")
    return {"question": question, "mode": mode, "constraints": constraints, "selector": selector,
            "results": results, "text": text, "map_path": map_path, "n_pts": n_pts}


def render_markdown(a: dict) -> str:
    rel = a["map_path"].name
    lines = [f"# {a['question']}", "",
             f"**Modo:** {a['mode']}  ·  **Filtro:** `{json.dumps(a['constraints'], ensure_ascii=False)}`"]
    if a.get("selector"):
        lines.append(f"**Criterio de selección:** {a['selector']}")
    lines += ["", "## Respuesta (grounded)", "", a["text"], "",
             "## Especies y evidencia", "",
             "| especie | familia | elev (m) | vertiente | Tomo·pág | GBIF n |",
             "|---|---|---|---|---|---|"]
    for f, _ in a["results"][:12]:
        n = len(gbif_map.get_points(f.species))
        flag = " ⚠️<5" if n < 5 else ""
        lines.append(f"| *{f.species}* | {f.family} | {f.elev_min}–{f.elev_max} | "
                     f"{', '.join(f.vertientes) or '–'} | {f.volume}·{f.pages} | {n}{flag} |")
    # "A" and "B→A" both rendered via single_species_map (the validated renderer);
    # plain "B" rendered via most_likely_map (GBIF-only evidence scatter).
    map_title = (f"Mapa de distribución (Manual + GBIF, n={a['n_pts']})"
                 if a["mode"].startswith("A") or a["mode"].startswith("B→A") else
                 f"Mapa GBIF — evidencia ({a['n_pts']} registros filtrados)")
    lines += ["", f"## {map_title}", "",
              f"![mapa](../maps/{rel})", "", "---", _DISCLAIMER]
    md = "\n".join(lines)
    out = _ANSWERS / f"answer_{abs(hash(a['question'])) % 10**8}.md"
    out.write_text(md, encoding="utf-8")
    return str(out)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "arbustos endémicos de bosque nuboso sobre 2000 m en Talamanca"
    a = answer(q)
    path = render_markdown(a)
    print(f"\nPREGUNTA: {q}\nMODO: {a['mode']}  |  {len(a['results'])} especies  |  "
          f"{a['n_pts']} registros GBIF\n")
    print(textwrap.shorten(a["text"], 400))
    print(f"\nreporte → {path}\nmapa    → {a['map_path']}")
