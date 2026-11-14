"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Check, Stage, UseCase } from "@/lib/types";

export const LABELS: Record<Stage, string> = { draft: "Draft", simulation: "Simulation", pilot: "Pilot",
                                               production: "Production" };
const EXECUTION: Record<string, string> = {
  draft: "Nothing runs: no run may start or continue.",
  simulation: "Runs allowed; only simulated systems are called.",
  pilot: "Runs allowed; simulated and sandbox systems are called, production systems never.",
};

export default function StageOverview({ workspace, useCase, admin, onChanged }: {
  workspace: string; useCase: UseCase; admin: boolean; onChanged: () => void;
}) {
  const at = useCase.stages.indexOf(useCase.stage);
  const next = useCase.stages[at + 1] as Stage | undefined;
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [to, setTo] = useState<Stage | "">(next && next !== "production" ? next : "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { setChecks(null); setError(""); setTo(next && next !== "production" ? next : ""); },
            [useCase.id, useCase.stage, next]);

  async function runChecks() {
    if (!next) return;
    try { setChecks((await api.checks(workspace, useCase.id, next)).checks); }
    catch (e) { setError((e as Error).message); }
  }

  async function move(ev: React.FormEvent) {
    ev.preventDefault();
    if (!to) return;
    setBusy(true); setError("");
    try {
      await api.move(workspace, useCase.id, to, reason);
      setReason("");
      onChanged();
    } catch (e) {
      setError((e as Error).message);
      if (e instanceof ApiError && Array.isArray(e.data.checks)) setChecks(e.data.checks as Check[]);
    } finally { setBusy(false); }
  }

  const warning = useCase.integrity_problem ?? (useCase.stale
    ? "The configuration changed after this stage was granted: the engine treats the use case as Draft until it is checked again."
    : null);

  return (
    <section aria-labelledby="ov-title" className="overview">
      <h2 id="ov-title">{useCase.name}</h2>
      <p className="muted small">
        {useCase.id} · {useCase.ontology} · fingerprint <code>{useCase.fingerprint.slice(0, 12)}</code> ·{" "}
        {useCase.origin === "template" ? `created from template ${useCase.template}` : "configured by the operator"}
      </p>
      <ol className="stepper" aria-label="Lifecycle stage">
        {useCase.stages.map((s, i) => (
          <li key={s} aria-current={i === at ? "step" : undefined}
              className={[i < at ? "done" : "", i === at ? "current" : "", s === "production" ? "locked" : ""].join(" ")}>
            {LABELS[s]}{s === "production" ? " (not authorised)" : ""}
          </li>
        ))}
      </ol>
      <p className="exec" data-testid="execution">
        <strong>Execution now:</strong> {EXECUTION[useCase.effective_stage] ?? EXECUTION.draft}
        <span className="source"> · enforced by the engine</span>
      </p>
      {warning && <p className="warn" role="alert">{warning}</p>}

      <div className="card">
        <div className="row spread">
          <h3>{next ? `Readiness for ${LABELS[next]}` : "Readiness"}</h3>
          <button type="button" onClick={runChecks} disabled={!next}>Check now</button>
        </div>
        {checks === null ? <p className="muted small">Checks are evaluated by the platform when you ask, and again at every move.</p> : (
          <ul className="checks">
            {checks.map((c) => (
              <li key={c.id} className={c.passed ? "pass" : "fail"}>
                <span className="sr-only">{c.passed ? "Passed: " : "Failed: "}</span>{c.detail}
              </li>
            ))}
          </ul>
        )}
      </div>

      {admin && (
        <form className="card" onSubmit={move} aria-labelledby="move-title">
          <h3 id="move-title">Change stage</h3>
          <label htmlFor="move-to">Move to</label>
          <select id="move-to" value={to} onChange={(e) => setTo(e.target.value as Stage)}>
            <option value="" disabled>Choose a stage</option>
            {useCase.stages.filter((s) => s !== useCase.stage).map((s) => {
              const i = useCase.stages.indexOf(s);
              return <option key={s} value={s} disabled={s === "production" || i > at + 1}>
                {LABELS[s]}{i < at ? " (back)" : ""}{s === "production" ? " (not authorised)" : ""}</option>;
            })}
          </select>
          <label htmlFor="move-reason">Reason (recorded with your name)</label>
          <textarea id="move-reason" required maxLength={500} rows={2} value={reason}
                    onChange={(e) => setReason(e.target.value)} />
          <button type="submit" className="primary" disabled={busy || !to}>Record the move</button>
          <p className="muted small">The platform re-checks everything when you submit; this form decides nothing.</p>
          {error && <p className="error" role="alert">{error}</p>}
        </form>
      )}

      <div className="card">
        <h3>Stage history</h3>
        {useCase.history && useCase.history.length > 0 ? (
          <ol className="history">
            {[...useCase.history].reverse().map((h) => (
              <li key={h.seq}>
                {LABELS[h.from_stage]} → {LABELS[h.to_stage]} by {h.by}, <time dateTime={h.at}>{new Date(h.at).toLocaleString()}</time>
                <br /><span className="muted small">{h.reason}</span>
              </li>
            ))}
          </ol>
        ) : <p className="muted small">No stage change yet.</p>}
      </div>
    </section>
  );
}
