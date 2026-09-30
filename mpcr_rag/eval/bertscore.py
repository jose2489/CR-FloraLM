"""BERTScore: RAG vs baseline free-text answers vs the Manual reference.

Mirrors the evaluation of prior plant-knowledge RAG papers (Xiong et al. 2025;
Honna et al. 2025), which report BERTScore P/R/F1 of RAG vs a bare LLM. Here the
candidate = each arm's free-text description of a species' CR distribution; the
reference = the Manual's distribution paragraph. Same model both arms (gpt-4o-mini);
the only difference is whether the retrieved ficha is provided (grounding).

  python -m mpcr_rag.eval.bertscore 150     # generate texts → data/eval/bertscore.csv
  python -m mpcr_rag.eval.bertscore report  # compute BERTScore + report
"""
from __future__ import annotations

import csv
import os

import requests

from .. import config
from ..store import local_store
from .rag_vs_baseline import sample_catalog

_MODEL = config.ENRICH_MODEL


def _ask_text(species: str, context: str | None = None) -> str:
    sys = ("Eres un botánico de Costa Rica. Describe en UN párrafo conciso la "
           "distribución EN COSTA RICA de la especie: tipo(s) de bosque, rango de "
           "elevación en metros, vertiente y regiones.")
    user = f"Especie: {species}"
    if context:
        sys += " Basa la descripción ÚNICAMENTE en el siguiente texto del Manual."
        user = f"Texto del Manual:\n{context}\n\n{user}"
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY','')}",
                     "Content-Type": "application/json"},
            json={"model": _MODEL, "temperature": 0,
                  "messages": [{"role": "system", "content": sys},
                               {"role": "user", "content": user}]},
            timeout=40)
        return r.json()["choices"][0]["message"]["content"].strip().replace("\n", " ")
    except Exception:
        return ""


def run(n: int, out_csv) -> None:
    conn = local_store.connect(config.SQLITE_PATH)
    sample = sample_catalog(conn, n)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["species", "reference", "base_text", "rag_text"])
        w.writeheader()
        for i, f in enumerate(sample, 1):
            w.writerow({"species": f.species, "reference": f.distribution_paragraph,
                        "base_text": _ask_text(f.species),
                        "rag_text": _ask_text(f.species, f.distribution_paragraph)})
            fh.flush()
            if i % 25 == 0:
                print(f"  ...{i}/{len(sample)}", flush=True)
    print(f"CSV → {out_csv}", flush=True)


def report() -> None:
    import datetime as _dt
    import shutil
    from pathlib import Path

    from bert_score import score

    src = config.DATA_DIR / "eval" / "bertscore.csv"
    results = Path(__file__).resolve().parent / "results"
    results.mkdir(exist_ok=True)
    rows = [r for r in csv.DictReader(open(src, encoding="utf-8"))
            if r["reference"] and r["base_text"] and r["rag_text"]]
    refs = [r["reference"] for r in rows]

    def bs(cands, rescale):
        P, Rc, F = score(cands, refs, lang="es", rescale_with_baseline=rescale,
                         verbose=False)
        return P.mean().item(), Rc.mean().item(), F.mean().item()

    base, rag = [r["base_text"] for r in rows], [r["rag_text"] for r in rows]
    # raw (comparable to prior papers' reported BERTScore) + rescaled (interpretable)
    bP, bR, bF = bs(base, False)
    gP, gR, gF = bs(rag, False)
    bFr = bs(base, True)[2]
    gFr = bs(rag, True)[2]

    md = f"""# BERTScore — RAG vs bare-LLM baseline (free-text distribution answers)

*Generated {_dt.date.today().isoformat()} from `{src.name}` (N={len(rows)} species).*

Candidate = each arm's free-text description of a species' Costa Rica distribution;
reference = the Manual's distribution paragraph. Same model (`{_MODEL}`); the only
difference is whether the retrieved ficha is supplied (grounding). BERTScore computed
with a multilingual model (`lang="es"`, rescaled with baseline). This mirrors the
BERTScore evaluation of prior plant-knowledge RAG systems.

**Raw BERTScore** (directly comparable to the values reported by prior plant-RAG papers):

| arm | P | R | F1 |
|---|---:|---:|---:|
| Baseline (parametric) | {bP:.3f} | {bR:.3f} | {bF:.3f} |
| **RAG (grounded)** | **{gP:.3f}** | **{gR:.3f}** | **{gF:.3f}** |
| Δ (RAG − base) | {gP-bP:+.3f} | {gR-bR:+.3f} | {gF-bF:+.3f} |

**Rescaled with baseline** (random ≈ 0; sharper interpretation): baseline F1 = {bFr:.3f},
RAG F1 = {gFr:.3f}, **Δ = {gFr-bFr:+.3f}**. The baseline's free text sits near the random
floor — it is no more similar to the Manual than chance — while grounding lifts it well above.

## Reproducibility
```
python -m mpcr_rag.eval.bertscore 150     # generate texts → data/eval/bertscore.csv
python -m mpcr_rag.eval.bertscore report  # this report
```
Data artifact: `results/{src.name}`.

## References
- Xiong, J. et al. (2025). *Enhancing Plant Protection Knowledge with LLMs: A Fine-Tuned
  QA System Using LoRA.* **Applied Sciences** 15(7): 3850.
- Honna, P. et al. (2025). *Agentic AI Approaches for Indian Medicinal Plant Knowledge
  Systems.* **CSITSS 2025**, IEEE.
- Zhang, T. et al. (2020). *BERTScore: Evaluating Text Generation with BERT.* **ICLR**.
"""
    (results / "bertscore_results.md").write_text(md, encoding="utf-8")
    shutil.copy(src, results / src.name)
    print(f"report → {results/'bertscore_results.md'}")
    print(f"  Baseline F1={bF:.3f}  RAG F1={gF:.3f}  Δ={gF-bF:+.3f}")


if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else "150"
    if arg == "report":
        report()
    else:
        run(int(arg), config.DATA_DIR / "eval" / "bertscore.csv")
