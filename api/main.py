"""
EL-EHB API.

Run:
    pip install -r requirements.txt
    uvicorn api.main:app --reload --port 8000

Then open http://localhost:8000/docs for the interactive API,
or open frontend/index.html directly in a browser (it calls this API).
"""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

sys.path.append(str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api import db
from harness.pipeline import ADAPTERS, run_evaluation
from harness.bias import run_bias_audit

app = FastAPI(title="EL-EHB API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    db.init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/adapters")
def adapters() -> dict:
    return {"available": list(ADAPTERS.keys())}


@app.post("/runs")
def create_run(adapter: str = "mock") -> dict:
    if adapter not in ADAPTERS:
        raise HTTPException(400, f"Unknown adapter '{adapter}'. Available: {list(ADAPTERS)}")

    results, metrics, model_name = run_evaluation(adapter)
    results_payload = [asdict(r) for r in results]

    # Run the bias audit against the one screening item tagged for it.
    from harness.pipeline import load_items, load_registry
    items = load_items()
    screening_item = next((it for it in items if it["id"] == "T4-SCREEN-006"), None)
    bias_summary = None
    if screening_item:
        adapter_instance = ADAPTERS[adapter]()
        audit = run_bias_audit(screening_item, adapter_instance, base_name="Priya Raman")
        bias_summary = {
            "four_fifths": audit.four_fifths_check(),
            "variants": [
                {"group": v.group, "name": v.name, "decision": v.decision, "response": v.response}
                for v in audit.variants
            ],
        }

    run_id = db.save_run(model_name, adapter, metrics, results_payload, bias_summary)
    return {"run_id": run_id, "model": model_name, "metrics": metrics, "bias": bias_summary}


@app.get("/runs")
def get_runs() -> list[dict]:
    return db.list_runs()


@app.get("/runs/{run_id}")
def get_run(run_id: int) -> dict:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/leaderboard")
def leaderboard() -> list[dict]:
    runs = db.list_runs()
    board = [
        {
            "run_id": r["id"],
            "model": r["model"],
            "fcs": r["metrics"]["factual_consistency_score"],
            "hallucination_rate": r["metrics"]["hallucination_rate"],
            "abstention_quality": r["metrics"]["abstention_quality"],
        }
        for r in runs
    ]
    return sorted(board, key=lambda x: x["fcs"], reverse=True)
