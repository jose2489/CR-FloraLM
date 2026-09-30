# RAG vs bare-LLM baseline — effect of grounding on geospatial QA

*Generated 2026-06-09 from `rag_vs_baseline.csv` (N=500 species).*

Per-species factual QA isolating **retrieval**: the same model answers each species'
Costa Rica distribution (elevation, vertiente, regions) as JSON, either from
parametric memory (**baseline**) or given the retrieved Manual ficha (**RAG**).
Ground truth = the Manual's extracted fields.

## Method
- **Model:** `openai/gpt-4o-mini` (OpenRouter), `temperature=0`, JSON output — *identical in both arms*.
- **Question:** "¿Cuál es la distribución en Costa Rica de *{especie}*?"
- **Baseline:** system prompt + question, no context.
- **RAG:** same + the ficha `distribution_paragraph` as context (answer grounded only on it).
- **Metrics:** elevation **IoU** (range intersection/union) and **midpoint error** (m, robust
  to single-point Manual ranges); **vertiente** exact match; **region recall**.
- **Sample:** 500 named species spread across families.

## Results (stratified)

### Todas (N=500)

| arm | elev IoU | elev err mediana (m) | vertiente | region recall |
|---|---:|---:|---:|---:|
| Baseline (paramétrico) | 34% | 400 | 47% | 76% |
| **RAG (grounded)** | **89%** | **0** | **95%** | **89%** |
| Δ (RAG − base) | +55% | -400 | +49% | +13% |

### Endémicas (N=89)

| arm | elev IoU | elev err mediana (m) | vertiente | region recall |
|---|---:|---:|---:|---:|
| Baseline (paramétrico) | 24% | 400 | 30% | 84% |
| **RAG (grounded)** | **91%** | **0** | **97%** | **93%** |
| Δ (RAG − base) | +67% | -400 | +67% | +9% |

### No endémicas (N=411)

| arm | elev IoU | elev err mediana (m) | vertiente | region recall |
|---|---:|---:|---:|---:|
| Baseline (paramétrico) | 36% | 400 | 50% | 74% |
| **RAG (grounded)** | **88%** | **0** | **95%** | **88%** |
| Δ (RAG − base) | +52% | -400 | +45% | +14% |


The gap is largest for **endemic** species — the long tail absent from the model's
parametric knowledge — and small for widespread species the model already knows,
isolating grounding as the cause.

## Illustrative cases (largest RAG gain)

| especie | Manual (m) | baseline IoU | RAG IoU |
|---|---:|---:|---:|
| *Anthurium carnosum* | 1700-2700 | 0% | 100% |
| *Catopsis juncifolia* | 50-1000 | 0% | 100% |
| *Vriesea heliconioides* | 0-900 | 0% | 100% |
| *Werauhia moralesii* | 800-1000 | 0% | 100% |
| *Tradescantia petricola* | 0-100 | 0% | 100% |
| *Carex guatemalensis* | 3400-3600 | 0% | 100% |

## Reproducibility
```
python -m mpcr_rag.eval.rag_vs_baseline 500     # run → data/eval/rag_vs_baseline.csv
python -m mpcr_rag.eval.rag_vs_baseline report  # this report
```
- Same model both arms; only difference = retrieved ficha context. Ground truth = Manual fields.
- Data artifact: `results/rag_vs_baseline.csv` (frozen per-species output).
