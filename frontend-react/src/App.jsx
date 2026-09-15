import React, { useEffect, useState, useCallback } from "react";
import {
  MetricsLedger,
  FailureTable,
  BiasExhibit,
  ItemExhibit,
  Leaderboard,
  formatModelName,
} from "./components.jsx";

const API = "http://localhost:8000";

export default function App() {
  const [adapter, setAdapter] = useState("mock");
  const [runs, setRuns] = useState([]);
  const [currentRun, setCurrentRun] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refreshRunsList = useCallback(async () => {
    const res = await fetch(`${API}/runs`);
    if (!res.ok) throw new Error("Could not load run history");
    setRuns(await res.json());
  }, []);

  const refreshLeaderboard = useCallback(async () => {
    const res = await fetch(`${API}/leaderboard`);
    if (!res.ok) throw new Error("Could not load leaderboard");
    setLeaderboard(await res.json());
  }, []);

  const loadRun = useCallback(async (runId) => {
    const res = await fetch(`${API}/runs/${runId}`);
    if (!res.ok) throw new Error(`Could not load run #${runId}`);
    setCurrentRun(await res.json());
  }, []);

  useEffect(() => {
    setError(null);
    Promise.all([refreshRunsList(), refreshLeaderboard()]).catch((e) =>
      setError(e.message + " — is the API running at " + API + "?")
    );
  }, [refreshRunsList, refreshLeaderboard]);

  async function handleRunEvaluation() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/runs?adapter=${adapter}`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      await Promise.all([refreshRunsList(), refreshLeaderboard(), loadRun(data.run_id)]);
    } catch (e) {
      setError("Run failed: " + e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="wordmark">
          EL-EHB
          <small>Employment LLM evaluation &amp; hallucination benchmark</small>
        </div>

        <div>
          <div className="field-label">Model under test</div>
          <select className="control" value={adapter} onChange={(e) => setAdapter(e.target.value)}>
            <option value="mock">mock (offline demo)</option>
            <option value="gemini">API</option>
          </select>
          <button className="run-btn" onClick={handleRunEvaluation} disabled={loading}>
            {loading ? "⏳ Running evaluation…" : "▶ Run evaluation"}
          </button>
        </div>

        {error && <div className="err-box">{error}</div>}

        <div className="docket">
          <div className="docket-title">Run history</div>
          {runs.length === 0 && <div className="empty-note">No runs yet.</div>}
          {runs.map((r) => (
            <div
              key={r.id}
              className={`docket-item ${currentRun?.id === r.id ? "active" : ""}`}
              onClick={() => loadRun(r.id)}
            >
              <div className="rid">#{r.id} · {formatModelName(r.model)}</div>
              <div className="rmeta">
                FCS {(r.metrics.factual_consistency_score * 100).toFixed(0)}%
              </div>
            </div>
          ))}
        </div>
      </aside>

      <main className="exhibit-room">
        <div className="case-header">
          <h1>{currentRun ? `Run #${currentRun.id}` : "No run selected"}</h1>
          <div className="filed">
            {currentRun
              ? `${formatModelName(currentRun.model)} · ${new Date(currentRun.created_at * 1000).toLocaleString()}`
              : "Run an evaluation from the sidebar to begin"}
          </div>
        </div>

        {currentRun && (
          <>
            <section className="exhibit-block">
              <h2 className="block-title">Metrics</h2>
              <MetricsLedger metrics={currentRun.metrics} />
            </section>

            <section className="exhibit-block">
              <h2 className="block-title">Failure distribution</h2>
              <FailureTable metrics={currentRun.metrics} />
            </section>

            <section className="exhibit-block">
              <h2 className="block-title">Bias audit — resume screening, name swapped only</h2>
              <BiasExhibit bias={currentRun.bias} />
            </section>

            <section className="exhibit-block">
              <h2 className="block-title">Per-item claim exhibits</h2>
              {currentRun.results.map((item) => (
                <ItemExhibit item={item} key={item.item_id} />
              ))}
            </section>
          </>
        )}

        <section className="exhibit-block">
          <h2 className="block-title">Leaderboard</h2>
          <Leaderboard rows={leaderboard} />
        </section>
      </main>
    </div>
  );
}
