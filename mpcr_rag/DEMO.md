# MPCR-RAG — Guía de demo (componente BIP)

Guía para presentarle a la tutora: qué mostrar, en qué orden, qué decir, y el
detalle de cada componente.

---

## 1. El pitch (30 segundos)

> Convertimos el **Manual de Plantas de Costa Rica** (5,791 especies, Tomos II–VI)
> en una base estructurada y consultable, y construimos un sistema **RAG** que
> responde preguntas geoespaciales en **lenguaje natural**, con **texto fundamentado
> con cita de página** y un **mapa de distribución**. Lo validamos contra ocurrencias
> reales de **GBIF** (97% de concordancia) y demostramos que el *grounding* mejora la
> exactitud geoespacial +55 puntos frente a un LLM solo.

---

## 2. Guion de demo en vivo (lo que se ejecuta)

**Catálogo (contexto):**
```bash
python -c "from mpcr_rag.store import local_store as L; from mpcr_rag import config as C; \
c=L.connect(C.SQLITE_PATH); print(c.execute('SELECT COUNT(*) FROM fichas').fetchone()[0],'especies,', \
c.execute('SELECT COUNT(DISTINCT family) FROM fichas').fetchone()[0],'familias')"
```

**Demo 1 — Pregunta NL → consulta estructurada (el núcleo).** Muestra cómo una
pregunta en español se convierte en un filtro estructurado + lista rankeada:
```bash
python -m mpcr_rag.query.answer  "arbustos endémicos de bosque nuboso sobre 2000 m en Talamanca"
```
*Qué señalar:* la línea `INTENT: {...}` es el filtro que el LLM extrajo (hábito,
bosque, región, elevación, endemismo). Eso es lo que un LLM solo o una búsqueda web
no resuelven de forma exacta.

**Demo 2 — Respuesta completa (texto grounded + mapa).** Pregunta combinatoria:
```bash
python -m mpcr_rag.query.answer "árboles de Lauraceae que florecen en enero en la vertiente Caribe"
```
*Qué señalar:* el texto cita (Tomo, página); se genera un mapa; hay disclaimer de
sesgo de colecta. Abre el `.md` y el `.png` que imprime.

**Demo 3 — Superlativo (B→A): elegir UNA especie.** Muestra el ruteo automático:
```bash
python -m mpcr_rag.query.answer "cuál es el árbol que crece a mayor altitud en la Cordillera de Talamanca"
```
*Resultado:* *Chusquea subtessellata* (bambú de páramo, 3000–3800 m) + mapa
detallado de distribución. El sistema detecta que se pide UNA especie y la elige
sobre la población filtrada completa (no sobre un top-k).

**Demo 4 — Mapa detallado de especie (validado con experto).** Abre
`mpcr_rag/data/maps/manual_*.png` (o `paper/figs/single_species_map.png`,
*Peltogyne purpurea*). Explica las capas: regiones del Manual ∩ máscara de
elevación (cyan), puntos GBIF, **regiones inferidas por GBIF** (cluster-flip),
áreas protegidas filtradas por elevación.

**Reportes de evaluación** (abrir, no ejecutar):
- `mpcr_rag/eval/results/manual_vs_gbif_results.md` — validación 97%.
- `mpcr_rag/eval/results/rag_vs_baseline_results.md` — RAG vs baseline.
- `mpcr_rag/eval/results/bertscore_results.md` — BERTScore.

---

## 3. `intent.py` explicado en detalle (la pieza que preguntaste)

**Rol:** traduce una pregunta en español al **vocabulario controlado** del catálogo,
produciendo un filtro de metadata exacto + el ruteo de la consulta.

**Flujo (`mpcr_rag/query/intent.py`):**
1. `load_vocab()` — lee de SQLite los valores **reales** del catálogo: hábitos,
   tipos de bosque, vertientes, regiones, familias. Esto es clave: el LLM solo puede
   elegir entre valores que existen, no inventa filtros.
2. `parse_intent(question)` — llama a un LLM (`gpt-4o-mini` vía OpenRouter,
   `temperature=0`, salida JSON forzada) con un *system prompt* + las listas
   permitidas + reglas de elevación ("entre X y Y", "sobre X", "bajo X").
3. `_validate()` — se queda **solo** con valores que existen en el vocabulario
   (`pick()`), parsea enteros de elevación/mes, el booleano de endemismo, y detecta
   si la pregunta es una **lista** o un **superlativo** (`intent_type`,
   `selector_criterion`, `selector_direction`).
4. Salida: un dict estructurado:
   ```json
   {"habit":"arbusto","forest_type":"nuboso","region":"Cordillera de Talamanca",
    "elev_lo":2000,"endemic":true,"intent_type":"list", ... ,"semantic_text":"..."}
   ```
   Los campos de filtro alimentan al `retriever`; `semantic_text` es la parte de
   texto libre para el ranking semántico; `intent_type`/`selector_*` rutean en
   `answer.py` (lista vs. superlativo).

**Por qué importa:** separa la *intención* (estructurada, verificable) de la
*generación* (texto), y al anclar el filtro al vocabulario real evita alucinaciones
en la parte que decide qué especies se devuelven.

---

## 4. Componentes en detalle

| Capa | Módulo | Qué hace |
|---|---|---|
| **Ingesta** | `ingest/ficha_segmenter.py` | PDF OCR → fichas por especie (bloques de layout; ancla en encabezado binomial + párrafo de distribución; 0 mal-capturas, ~99% cobertura) |
| | `ingest/field_extractor.py` | ficha → campos estructurados (reusa `build_ficha`: elevación+outliers, vertiente, regiones, bosque, fenología; hábito con herencia de género; **familia resuelta vía GBIF backbone**) |
| | `ingest/build_catalog.py` | orquesta toda la ingesta → SQLite + Pinecone |
| **Esquema** | `schema.py` | dataclasses `Ficha` / `RawFicha` |
| **Almacén** | `store/local_store.py` | SQLite (fichas completas, hidratación por id) |
| | `store/pinecone_client.py` | índice Pinecone (e5-large alojado, metadata filtrable) |
| **Consulta** | `query/intent.py` | NL → intención estructurada (sección 3) |
| | `query/retriever.py` | Pattern A (especie), Pattern B (filtro+ranking), `filter_all` (población completa para superlativos), ranking por solape de elevación |
| | `query/gbif_map.py` | GBIF (resolución de taxón, limpieza de coordenadas, DEM), mapas de ocurrencia, conteos del snapshot DOI, mapa detallado vía `renderer` |
| | `query/answer.py` | end-to-end: rutea lista/superlativo, compone texto grounded con citas, mapa, disclaimer |
| **Evaluación** | `eval/manual_vs_gbif.py` | validación Manual↔GBIF (mediana/núcleo robusto) |
| | `eval/rag_vs_baseline.py` | RAG vs LLM solo (IoU, vertiente, region recall) |
| | `eval/bertscore.py` | BERTScore (comparabilidad con papers previos) |
| | `eval/make_report.py`, `gbif_download.py` | reportes reproducibles + DOI de GBIF |

---

## 5. Cambios recientes (sin commitear) — para revisar

Trabajo en progreso, funcional tras un fix de `ask()` en `intent.py`:
- **Familia resuelta por género** (`field_extractor.py`): varios PDFs agrupan varias
  familias por archivo; el nombre de archivo etiquetaba mal. Ahora la familia se
  resuelve del género real vía el backbone de GBIF → catálogo pasó a **189 familias**
  correctas (antes ~33 + etiquetas "Vol IV").
- **Consultas superlativas** (`retriever.filter_all` + `answer._select_superlative`):
  preguntas que piden UNA especie ("la que crece a mayor altitud", "la más común")
  sobre la población filtrada completa; criterios: elev_max/min, n_regiones,
  gbif_count.
- **Conteos GBIF del snapshot** (`gbif_map.py`): usa el download DOI congelado
  (1.01M registros) para contar ocurrencias por especie sin pegarle a la API por
  cada candidato.
- **Mapa detallado** integrado en `answer.py` para la respuesta de una sola especie.

> Recomendación: una vez revisado, commitear estos cambios (catálogo + features) en
> el branch `mpcr-rag` antes de seguir.

---

## 6. El paper

Borrador IEEE/inglés/doble-ciego en `mpcr_rag/paper/` (local, no en GitHub): sistema,
3 evaluaciones, 38 referencias, 5 ecuaciones, 4 figuras, DOI de datos. Listo para
Overleaf.
