# EL-EHB — Employment LLM Evaluation & Hallucination Benchmark

Benchmarks LLMs on employment-domain tasks (statutory QA, policy grounding,
resume extraction, job matching) and scores every response at the **claim
level** against a grounded corpus, classifying failures into a six-class
hallucination taxonomy. Includes a counterfactual bias audit.

## What's included

```
elehb/
├── benchmark/
│   ├── items.jsonl              # benchmark items (edit/extend this)
│   └── citation_registry.json   # valid statutory citations per jurisdiction
├── harness/
│   ├── pipeline.py               # claim extraction, verification, scoring, CLI
│   └── bias.py                   # counterfactual demographic perturbation
├── api/
│   ├── main.py                   # FastAPI app
│   └── db.py                     # SQLite persistence
├── frontend-react/                # React dashboard (recommended)
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components.jsx
│   │   └── index.css
│   └── package.json
├── frontend/
│   └── index.html                # plain HTML/JS dashboard (no Node.js needed)
└── requirements.txt
```

There are two frontends. Use whichever fits your setup:

- **`frontend-react/`** — a proper React app (Vite). Needs Node.js installed. This is the one to use if you want to keep building on it.
- **`frontend/index.html`** — a single static file, no build step, no Node.js. Open it directly in a browser. Useful if you just want to see it work quickly.

Both talk to the same backend and show the same data — pick one, you don't need both running.

## Quickstart (no API key needed — uses the mock model)

```bash
pip install -r requirements.txt

# Option A: run from the command line
python -m harness.pipeline --adapter mock

# Option B: run the full app
uvicorn api.main:app --reload --port 8000
```

Leave that running, then in a **second terminal**, start whichever frontend you want:

**React frontend:**
```bash
cd frontend-react
npm install
npm run dev
```
Open the URL it prints (usually `http://localhost:5173`).

**Plain HTML frontend:**
Just double-click `frontend/index.html`, or serve it to avoid browser file-access restrictions:
```bash
cd frontend
python3 -m http.server 5500
```
Open `http://localhost:5500`.

The API docs are auto-generated at `http://localhost:8000/docs`.

## Running against a real model

```bash
export GEMINI_API_KEY=AIzaSy...
python -m harness.pipeline --adapter gemini
# or select "gemini" from the dropdown in the dashboard
```

Add more adapters in `harness/pipeline.py` by implementing a class with a
single `generate(item) -> str` method and registering it in `ADAPTERS`.

## How scoring works

1. **Claim extraction** — splits each response into atomic, checkable claims.
2. **Hybrid verification**, hardest evidence first:
   - citation resolver (does the cited section actually exist?)
   - deterministic staleness check (superseded facts)
   - jurisdiction tripwire (doctrine from the wrong jurisdiction)
   - forbidden-fact check against the item's gold data
   - lexical grounding against the source document (fallback)
3. **Taxonomy classification** into H1–H6 (see `harness/pipeline.py::H_LABELS`).
4. **Aggregation** into Factual Consistency Score, hallucination rate,
   abstention quality, and citation validity rate.

Swap `check_grounding` in `pipeline.py` for an NLI model when you're ready —
the function signature is the only contract the rest of the pipeline relies on.

## Extending the benchmark

Add a line to `benchmark/items.jsonl`:

```json
{"id": "T1-XX-999", "task": "T1_statutory_qa", "jurisdiction": "IN-TN",
 "effective_from": "2025-01-01", "effective_to": null, "answerable": true,
 "prompt": "...", "context": null, "gold_answer": "...",
 "gold_facts": ["..."], "valid_citations": ["..."], "forbidden": ["..."],
 "numeric_gold": {}}
```

Set `"answerable": false` for trap items where the correct behaviour is to
decline — these score abstention as success, not failure.

## Known limitations (be upfront about these in your writeup)

- Grounding verification is lexical-overlap based, not a trained NLI model —
  good enough for a first build, not for production.
- The bias module perturbs one axis (name) on one task family (screening).
- Benchmark currently ships with a handful of hand-written items; real
  evaluation needs hundreds per task family for statistical confidence.
