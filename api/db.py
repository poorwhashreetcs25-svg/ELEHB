"""Minimal SQLite persistence. Swap for Postgres later by changing only
this file -- the API layer talks to these functions, not to SQL directly."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "elehb.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT NOT NULL,
    adapter TEXT NOT NULL,
    created_at REAL NOT NULL,
    metrics_json TEXT NOT NULL,
    results_json TEXT NOT NULL,
    bias_json TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.execute(SCHEMA)
    conn.commit()
    conn.close()


def save_run(model: str, adapter: str, metrics: dict, results: list[dict], bias: dict | None = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO runs (model, adapter, created_at, metrics_json, results_json, bias_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (model, adapter, time.time(), json.dumps(metrics), json.dumps(results), json.dumps(bias) if bias else None),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def list_runs() -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, model, adapter, created_at, metrics_json FROM runs ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "model": r["model"],
            "adapter": r["adapter"],
            "created_at": r["created_at"],
            "metrics": json.loads(r["metrics_json"]),
        }
        for r in rows
    ]


def get_run(run_id: int) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "model": row["model"],
        "adapter": row["adapter"],
        "created_at": row["created_at"],
        "metrics": json.loads(row["metrics_json"]),
        "results": json.loads(row["results_json"]),
        "bias": json.loads(row["bias_json"]) if row["bias_json"] else None,
    }
