import React, { useState } from "react";

export const H_LABELS = {
  H1: "Intrinsic — contradicts source",
  H2: "Extrinsic — unsupported addition",
  H3: "Legal fabrication",
  H4: "Jurisdiction drift",
  H5: "Temporal staleness",
  H6: "Overconfident non-abstention",
};

export function MetricsLedger({ metrics }) {
  if (!metrics) return null;
  const fcsGood = metrics.factual_consistency_score > 0.7;
  const hallGood = metrics.hallucination_rate < 0.3;
  return (
    <div className="ledger">
      <div className="ledger-cell">
        <div className="l-label">Factual consistency</div>
        <div className={`l-value ${fcsGood ? "good" : "bad"}`}>
          {(metrics.factual_consistency_score * 100).toFixed(1)}%
        </div>
      </div>
      <div className="ledger-cell">
        <div className="l-label">Hallucination rate</div>
        <div className={`l-value ${hallGood ? "good" : "bad"}`}>
          {(metrics.hallucination_rate * 100).toFixed(1)}%
        </div>
      </div>
      <div className="ledger-cell">
        <div className="l-label">Citation validity</div>
        <div className="l-value">
          {metrics.citation_validity_rate != null
            ? `${(metrics.citation_validity_rate * 100).toFixed(0)}%`
            : "n/a"}
        </div>
      </div>
      <div className="ledger-cell">
        <div className="l-label">Abstention quality</div>
        <div className="l-value">
          {metrics.abstention_quality >= 0 ? "+" : ""}
          {metrics.abstention_quality.toFixed(2)}
        </div>
      </div>
    </div>
  );
}

export function FailureTable({ metrics }) {
  if (!metrics) return null;
  const rows = Object.entries(metrics.failure_distribution).filter(([, c]) => c);
  return (
    <table className="ledger-table">
      <thead>
        <tr>
          <th>Class</th>
          <th>Description</th>
          <th>Count</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr>
            <td colSpan={3} className="empty-note">No failures detected in this run.</td>
          </tr>
        )}
        {rows.map(([cls, count]) => (
          <tr key={cls}>
            <td><span className="tag">{cls}</span></td>
            <td>{H_LABELS[cls]}</td>
            <td>{count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function BiasExhibit({ bias }) {
  if (!bias) return <div className="empty-note">No bias-eligible item in this run.</div>;
  const { four_fifths, variants } = bias;
  return (
    <div>
      <span className={`bias-verdict ${four_fifths.passes ? "pass" : "fail"}`}>
        four-fifths ratio {four_fifths.ratio.toFixed(2)} — {four_fifths.passes ? "pass" : "fail"}
      </span>
      <div className="variant-grid">
        {variants.map((v) => (
          <div className="variant-card" key={v.group}>
            <div className="v-group">{v.group.replace(/_/g, " ")} — {v.name}</div>
            <div className={`v-decision ${v.decision}`}>{v.decision}</div>
            <div className="v-response">{v.response}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ClaimRow({ claim }) {
  return (
    <div className="claim-row">
      <div className={`stamp ${claim.verdict}`}>
        {claim.verdict}{claim.h_class ? ` · ${claim.h_class}` : ""}
      </div>
      <div className="claim-text">
        {claim.text}
        {claim.reason && <div className="claim-reason">{claim.reason}</div>}
      </div>
    </div>
  );
}

export function ItemExhibit({ item }) {
  const [open, setOpen] = useState(false);
  const badCount = item.claims.filter((c) => c.verdict !== "SUPPORTED").length;
  const status = badCount
    ? `${badCount} issue${badCount > 1 ? "s" : ""}`
    : item.claims.length
    ? "all supported"
    : item.abstained
    ? "abstained"
    : "n/a";

  return (
    <div className="item-exhibit">
      <div className="item-exhibit-head" onClick={() => setOpen((o) => !o)}>
        <div>
          <div className="ex-id">{item.item_id} — {item.task}</div>
          <div className="ex-meta">{item.jurisdiction}{item.abstained ? " · abstained" : ""}</div>
        </div>
        <div className="ex-status">{open ? "▾" : "▸"} {status}</div>
      </div>
      {open && (
        <div className="item-exhibit-body">
          <div className="response-quote">{item.response}</div>
          {item.claims.length === 0 && (
            <div className="empty-note">No claims extracted for this item.</div>
          )}
          {item.claims.map((c, i) => (
            <ClaimRow claim={c} key={i} />
          ))}
        </div>
      )}
    </div>
  );
}

export function formatModelName(name) {
  if (!name) return "";
  if (name.toLowerCase().includes("gemini")) return "API";
  return name;
}

export function Leaderboard({ rows }) {
  if (!rows || rows.length === 0) {
    return <div className="empty-note">No runs yet.</div>;
  }
  const maxFcs = Math.max(...rows.map((r) => r.fcs));
  return (
    <table className="ledger-table">
      <thead>
        <tr>
          <th>Run</th>
          <th>Model</th>
          <th>Factual consistency</th>
          <th>Hallucination rate</th>
          <th>Abstention quality</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.run_id} className={`leaderboard-row ${r.fcs === maxFcs ? "leader" : ""}`}>
            <td>#{r.run_id}</td>
            <td>{formatModelName(r.model)}</td>
            <td>{(r.fcs * 100).toFixed(1)}%</td>
            <td>{(r.hallucination_rate * 100).toFixed(1)}%</td>
            <td>{r.abstention_quality.toFixed(2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
