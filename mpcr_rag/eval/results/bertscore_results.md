# BERTScore — RAG vs bare-LLM baseline (free-text distribution answers)

*Generated 2026-06-09 from `bertscore.csv` (N=150 species).*

Candidate = each arm's free-text description of a species' Costa Rica distribution;
reference = the Manual's distribution paragraph. Same model (`openai/gpt-4o-mini`); the only
difference is whether the retrieved ficha is supplied (grounding). BERTScore computed
with a multilingual model (`lang="es"`, rescaled with baseline). This mirrors the
BERTScore evaluation of prior plant-knowledge RAG systems.

**Raw BERTScore** (directly comparable to the values reported by prior plant-RAG papers):

| arm | P | R | F1 |
|---|---:|---:|---:|
| Baseline (parametric) | 0.629 | 0.612 | 0.620 |
| **RAG (grounded)** | **0.708** | **0.686** | **0.697** |
| Δ (RAG − base) | +0.078 | +0.074 | +0.076 |

**Rescaled with baseline** (random ≈ 0; sharper interpretation): baseline F1 = -0.038,
RAG F1 = 0.171, **Δ = +0.209**. The baseline's free text sits near the random
floor — it is no more similar to the Manual than chance — while grounding lifts it well above.

## Reproducibility
```
python -m mpcr_rag.eval.bertscore 150     # generate texts → data/eval/bertscore.csv
python -m mpcr_rag.eval.bertscore report  # this report
```
Data artifact: `results/bertscore.csv`.

## References
- Xiong, J. et al. (2025). *Enhancing Plant Protection Knowledge with LLMs: A Fine-Tuned
  QA System Using LoRA.* **Applied Sciences** 15(7): 3850.
- Honna, P. et al. (2025). *Agentic AI Approaches for Indian Medicinal Plant Knowledge
  Systems.* **CSITSS 2025**, IEEE.
- Zhang, T. et al. (2020). *BERTScore: Evaluating Text Generation with BERT.* **ICLR**.
