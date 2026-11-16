"use client";

// Stored simulation runs of a use case. Studio asks and shows; the engine starts, pauses, resumes, cancels and
// audits each run through its existing execution lifecycle, on the active release, and decides who may start,
// see or decide what. Every tool here is simulated: a completed run is not evidence that a real system changed.

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, runs as engine, ApiError } from "@/lib/api";
import { cancellable, mayDecide, releaseOf, resumable, statusClass, stepLine, trace, STATUS_TEXT } from "@/lib/runs";
import type { EngineMe, ObjectRow, ReviewView, RunAudit, RunRow, RunView } from "@/lib/runs";
import type { OntologySummary, ReleaseState, UseCase } from "@/lib/types";
import SampleRecords from "./SampleRecords";

type Templates = Record<string, { root: string; entities: string[] }>;

export default function RunsView({ workspace, useCase, onChanged }: { workspace: string; useCase: UseCase; onChanged?: () => void }) {
  const path = useCase.path;
  const [me, setMe] = useState<EngineMe | null>(null);
  const [model, setModel] = useState<OntologySummary | null>(null);
  const [releases, setReleases] = useState<ReleaseState | null>(null);
  const [rows, setRows] = useState<RunRow[]>([]);
  const [records, setRecords] = useState<ObjectRow[]>([]);
  const [template, setTemplate] = useState("");
  const [root, setRoot] = useState("");
  const [run, setRun] = useState<RunView | null>(null);
  const [review, setReview] = useState<ReviewView | null>(null);
  const [audit, setAudit] = useState<RunAudit | null>(null);
  const [comment, setComment] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const can = useCallback((p: string) => !!me && (me.permissions.includes(p) || me.permissions.includes("admin")), [me]);
  const templates: Templates = useMemo(() => ((model as any)?.case_templates ?? {}) as Templates, [model]);

  const attempt = useCallback(async (work: () => Promise<void>) => {
    setBusy(true); setError(""); setMessage("");
    try { await work(); }
    catch (e) { setError(e instanceof ApiError ? e.message : (e as Error).message); }
    finally { setBusy(false); }
  }, []);

  const list = useCallback(async (who: EngineMe | null) => {
    if (who && (who.permissions.includes("read") || who.permissions.includes("admin"))) setRows((await engine.list(path)).items);
  }, [path]);

  useEffect(() => {
    void attempt(async () => {
      const who = await engine.me(path);
      setMe(who);
      const [m, rel] = await Promise.all([api.ontology(path), api.releases(workspace, useCase.id)]);
      setModel(m); setReleases(rel);
      const names = Object.keys(((m as any).case_templates ?? {}) as Templates);
      if (names.length) setTemplate(names[0]);
      await list(who);
    });
  }, [path, workspace, useCase.id, attempt, list]);

  // the records a run can start from: those of the chosen case template's root entity that the caller may see
  useEffect(() => {
    const entity = templates[template]?.root;
    if (!entity || !can("read")) { setRecords([]); return; }
    let live = true;
    engine.objects(path, entity).then((r) => { if (live) { setRecords(r.items); setRoot((cur) => (r.items.some((i) => i.id === cur) ? cur : r.items[0]?.id ?? "")); } })
      .catch((e) => { if (live) setError((e as Error).message); });
    return () => { live = false; };
  }, [template, templates, path, can]);

  const show = useCallback(async (view: RunView) => {
    setRun(view); setAudit(null); setReview(null); setComment(""); setReason("");
    if (view.hidden) return;
    if (view.pending_review && can("review")) {
      const pending = (await engine.reviews(path)).items.find((r) => r.review_id === view.pending_review);
      setReview(pending ?? null);
    }
    if (can("audit")) setAudit(await engine.audit(path, view.run_id));
  }, [path, can]);

  const open = (id: string) => attempt(async () => { await show(await engine.get(path, id)); });
  const after = async (view: RunView, text: string) => { await show(view); await list(me); setMessage(text); onChanged?.(); };

  const start = () => attempt(async () => {
    const view = await engine.start(path, { case_template: template, root });
    await after(view, `Run ${view.run_id} is stored: ${STATUS_TEXT[view.status] ?? view.status}.`);
  });
  const decide = (approved: boolean) => attempt(async () => {
    if (!review) return;
    await after(await engine.decide(path, review.review_id, approved, comment), approved ? "Approval recorded: the run continued." : "Refusal recorded: the action was not performed.");
  });
  const resume = () => attempt(async () => { if (run) await after(await engine.resume(path, run.run_id), "The run was resumed."); });
  const cancel = () => attempt(async () => { if (run) await after(await engine.cancel(path, run.run_id, reason), "The run was cancelled. Nothing it had done was undone; nothing further will happen."); });

  const runnable = useCase.effective_stage !== "draft";  // advisory: the engine enforces the stage at every run
  const active = releases?.active ?? null;
  const number = run && releases ? releaseOf(run, releases.items) : null;
  const events = audit ? trace(audit.entries) : [];

  return (
    <div className="runs" data-testid="runs">
      <p className="notice small" role="note" data-testid="runs-notice">
        Persistent simulation. Each run is stored by the engine with its audit chain and runs on the active release
        {active ? <> (release <strong>{active.number}</strong>)</> : " (none yet)"}. The tools are simulated: nothing here contacts or
        changes a real system, and a completed run is not proof that one was changed. Production execution is not available.
      </p>
      {!runnable && <p className="warn" role="status" data-testid="runs-blocked">
        Runs are not possible now: the use case counts as Draft{useCase.stage !== "draft" ? " (what runs is not the active release)" : ""}.
        Activate an approved release and move the use case to Simulation in Overview; the engine refuses runs until then.</p>}
      {error && <p className="error" role="alert" data-testid="runs-error">{error}</p>}
      {message && <p className="ok small" role="status" data-testid="runs-message">{message}</p>}

      <SampleRecords workspace={workspace} useCaseId={useCase.id} onLoaded={() => setTemplate((t) => t)} />
      <section className="card" aria-labelledby="run-start">
        <h3 id="run-start">Start a simulation run</h3>
        {!can("run") ? <p className="muted small" data-testid="runs-denied">You do not have permission to start runs on this use case.
          An administrator can propose the <code>run</code> permission for you in Access; another person approves it.</p>
          : !Object.keys(templates).length ? <p className="muted small" data-testid="runs-no-template">The active model has no case template: a run needs one to read its case from the records. Add one in the model and release it.</p>
          : (
            <div className="row">
              <label htmlFor="run-template">Case</label>
              <select id="run-template" value={template} onChange={(e) => setTemplate(e.target.value)}>
                {Object.keys(templates).map((t) => <option key={t} value={t}>{t} (from a {templates[t].root})</option>)}
              </select>
              <label htmlFor="run-root">Record</label>
              <select id="run-root" value={root} onChange={(e) => setRoot(e.target.value)}>
                {records.map((r) => <option key={r.id} value={r.id}>{r.id}{r.attributes.status ? ` · ${String(r.attributes.status)}` : ""}</option>)}
              </select>
              <button type="button" className="primary" disabled={busy || !root || !runnable} onClick={start} data-testid="start-run">
                Start a stored run</button>
              {!records.length && <span className="muted small">No record of this kind is visible to you (sample records come with the released configuration).</span>}
            </div>
          )}
      </section>

      <div className="runs-body">
        <section aria-labelledby="run-list">
          <h3 id="run-list">Stored runs</h3>
          {!can("read") ? <p className="muted small">You do not have permission to read runs.</p> : (
            <ul className="uc-list" data-testid="run-list">
              {rows.map((r) => (
                <li key={r.run_id}><button type="button" aria-current={run?.run_id === r.run_id ? "true" : undefined} onClick={() => open(r.run_id)}>
                  <span>{r.case_id}<br /><span className="muted small">{r.run_id} · {r.started_by ?? "—"} · {r.created_at.slice(0, 19).replace("T", " ")}</span></span>
                  <span className={`pill ${statusClass(r.status)}`}>{STATUS_TEXT[r.status] ?? r.status}</span>
                </button></li>
              ))}
              {!rows.length && <li className="muted small">No run yet.</li>}
            </ul>
          )}
        </section>

        <section aria-labelledby="run-detail" data-testid="run-detail">
          <h3 id="run-detail">{run ? `Run ${run.run_id}` : "Execution"}</h3>
          {!run ? <p className="muted">Start a run or choose one.</p> : run.hidden ? <p className="muted">{run.detail}</p> : (
            <>
              <p className="small">
                <span className={`pill ${statusClass(run.status)}`} data-testid="run-status">{run.status}</span>{" "}
                {STATUS_TEXT[run.status] && STATUS_TEXT[run.status] !== run.status ? `${STATUS_TEXT[run.status]} · ` : ""}goal <code>{run.goal}</code> · case <code>{run.case_id}</code>
                {run.started_by ? ` · started by ${run.started_by}` : ""}
                <br /><span data-testid="run-release">{number !== null ? `Release ${number}` : "No release matches"} · configuration <code>{(run.configuration ?? "").slice(0, 12) || "—"}</code></span>
                {" · "}<span data-testid="run-effects">{run.simulated ? "simulated effects only: no other system was contacted" : "effects: see each step"}</span>
                {" · "}audit chain {run.audit_verified ? "verifies" : "DOES NOT VERIFY"}
              </p>
              <h4>Timeline</h4>
              <ol className="timeline" data-testid="run-steps">
                {(run.steps ?? []).map((s) => (
                  <li key={s.index}><strong>{s.action}</strong> <span className="muted">{stepLine(s)}</span>
                    {s.explanation && <div className="muted small">{s.explanation}</div>}
                    {s.message && <div className="small">{s.message}</div>}</li>
                ))}
                {!(run.steps ?? []).length && <li className="muted">No action was performed.</li>}
              </ol>
              {run.escalation && <p className="warn small" role="status" data-testid="run-escalation">
                {run.escalation.reason}{run.escalation.action ? ` (${run.escalation.action})` : ""}
                {run.escalation.details?.length ? `: ${run.escalation.details.join("; ")}` : ""}</p>}

              {run.pending_review && (
                <div className="card" data-testid="pending-review-card">
                  <h4>A person must decide{review ? `: ${review.action}` : ""}</h4>
                  {review ? (
                    <>
                      <p className="small">For {review.reviewers.join(", ")}. {(review.request.reasons ?? []).join("; ")}
                        {review.request.rule_ids?.length ? ` (${review.request.rule_ids.join(", ")})` : ""}</p>
                      {review.request.facts && <p className="muted small">Facts: {Object.entries(review.request.facts).map(([k, v]) => `${k} = ${String(v)}`).join(", ")}</p>}
                      {mayDecide(me, review, run) ? (
                        <div className="row">
                          <label className="sr-only" htmlFor="rv-comment">Comment</label>
                          <input id="rv-comment" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="comment (kept with the decision)" maxLength={500} />
                          <button type="button" className="primary" disabled={busy} onClick={() => decide(true)} data-testid="approve-review">Approve</button>
                          <button type="button" disabled={busy} onClick={() => decide(false)} data-testid="decline-review">Refuse</button>
                        </div>
                      ) : <p className="muted small" data-testid="review-not-yours">You cannot decide this review: it needs a person holding
                          {" "}{review.reviewers.join(" or ")} who did not start the run.</p>}
                    </>
                  ) : <p className="muted small" data-testid="review-not-yours">The run waits for a reviewer. You do not hold the reviewer role, so the review is not shown to you.</p>}
                </div>
              )}

              {(cancellable(run.status) || resumable(run.status)) && can("run") && (
                <div className="row">
                  {resumable(run.status) && <button type="button" disabled={busy} onClick={resume} data-testid="resume-run">Resume now</button>}
                  <label className="sr-only" htmlFor="cancel-reason">Reason for cancelling</label>
                  <input id="cancel-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="reason for cancelling" maxLength={500} />
                  <button type="button" disabled={busy || !reason.trim()} onClick={cancel} data-testid="cancel-run">Cancel the run</button>
                </div>
              )}

              <details open>
                <summary>Records after the run (as you may see them)</summary>
                <pre className="small scroll" data-testid="run-state">{JSON.stringify(run.state, null, 1)}</pre>
              </details>
              <details>
                <summary>Decision trace and audit evidence</summary>
                {audit ? (
                  <>
                    <p className="small" data-testid="audit-verified">{audit.entries.length} signed entries; the chain {audit.verified ? "verifies" : "DOES NOT VERIFY"}.</p>
                    <ol className="small audit" data-testid="audit-trace">
                      {events.map((e) => <li key={e.seq}><strong>{e.label}</strong> {e.detail}</li>)}
                    </ol>
                  </>
                ) : <p className="muted small" data-testid="audit-denied">The audit chain is shown to people with the <code>audit</code> permission.</p>}
              </details>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
