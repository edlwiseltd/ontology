"use client";

// Guided onboarding, one flow: business description → questions → visual review → engine validation → agents and
// simulated tools → dry run → release → stored simulation runs → readiness and audit. Studio only asks and shows.
// The engine validates every proposed item and every configuration, stores each revision, decides what runs and
// who may decide, and computes readiness; the platform governs releases. No language model is involved until the
// owner approves a provider (the sandbox architect answers), and every tool is simulated.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, architect, ApiError, type SimulatedDecision } from "@/lib/api";
import { ontologyToGraph } from "@/lib/graph";
import { documentToSummary } from "@/lib/model";
import { accessLines, countByKind, generatorLabel, itemLabel, preview, SAMPLE_BRIEF, standing, withProvenance,
         workflow } from "@/lib/onboarding";
import type { ArchitectStatus, Draft, DraftSimulation, ModelDocument, Proposal, Readiness, ReleaseState, UseCase,
              Validation } from "@/lib/types";
import AgentsView from "./AgentsView";
import ReleasesView from "./ReleasesView";
import RunsView from "./RunsView";
import StageOverview from "./StageOverview";

const STEPS = ["Describe", "Questions", "Review", "Confirm", "Agents & tools", "Dry run", "Release", "Stored runs",
               "Readiness"] as const;
const [AGENTS, DRY_RUN, RELEASE, RUNS, READINESS] = [4, 5, 6, 7, 8];

export default function OnboardingView({ workspace, useCase, admin, member, onChanged }: {
  workspace: string; useCase: UseCase; admin: boolean; member: string; onChanged: () => void }) {
  const path = useCase.path;
  const [step, setStep] = useState(0);
  const [status, setStatus] = useState<ArchitectStatus | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [brief, setBrief] = useState(SAMPLE_BRIEF);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [validation, setValidation] = useState<Validation | null>(null);
  const [saved, setSaved] = useState<string>("");
  const [decisions, setDecisions] = useState<SimulatedDecision[]>([]);
  const [simulation, setSimulation] = useState<DraftSimulation | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [subject, setSubject] = useState("active");
  const [releases, setReleases] = useState<ReleaseState | null>(null);
  const [stored, setStored] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = useCallback(async (work: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await work(); }
    catch (e) { setError(e instanceof ApiError ? e.message : (e as Error).message); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => {
    void run(async () => {
      const [listed, d] = await Promise.all([architect.list(path), api.draft(path)]);
      setStatus(listed.architect); setDraft(d); setStored(listed.items[0]?.id);
    });
  }, [path, run]);

  const confirmed: ModelDocument = useMemo(() => draft?.document ?? {}, [draft]);
  const selected = useMemo(() => (proposal?.items ?? []).filter((i) => chosen.has(i.id)), [proposal, chosen]);
  const previewed = useMemo(() => preview(confirmed, selected), [confirmed, selected]);
  const marks = useMemo(() => standing(confirmed, previewed), [confirmed, previewed]);
  const flow = useMemo(() => workflow(previewed), [previewed]);
  const access = useMemo(() => accessLines(previewed), [previewed]);
  const graph = useMemo(() => ontologyToGraph(documentToSummary(previewed)), [previewed]);
  const nodes: Node[] = graph.nodes.map((n) => ({
    id: n.id, position: n.position, draggable: false, className: marks[n.id] === "proposed" ? "proposed" : "confirmed",
    data: { label: `${n.id} · ${marks[n.id] === "proposed" ? "proposed" : "confirmed"}` },
    ariaLabel: `Entity ${n.id}, ${marks[n.id]}`,
  }));
  const names = new Set(Object.keys(previewed.entities ?? {}));
  const edges: Edge[] = (previewed.relationships ?? []).map((r: any, i: number) => ({ r, i }))
    .filter(({ r }: any) => names.has(r.from) && names.has(r.to))
    .map(({ r, i }: any) => ({ id: `r${i}`, source: r.from, target: r.to, label: r.type, labelStyle: { fontSize: 11 } }));

  function received(p: Proposal) {
    setProposal(p); setChosen(new Set(p.items.map((i) => i.id)));
    setValidation(null); setSaved(""); setSimulation(null); setDecisions([]);
  }

  const propose = () => run(async () => { received(await architect.propose(path, brief, confirmed)); setStep(1); });

  const revise = () => run(async () => {
    if (!proposal?.id) return;
    const given = Object.entries(answers).filter(([, v]) => v.trim()).map(([id, answer]) => ({ id, answer }));
    received(await architect.revise(path, proposal.id, given, confirmed));
    setStep(2);
  });

  const validate = () => run(async () => {
    setValidation((await api.validate(path, previewed)).validation);
    setStep(3);
  });

  const save = () => run(async () => {
    if (!proposal?.id || !draft) return;
    const document = withProvenance(previewed, proposal as Required<Pick<Proposal, "id" | "revision" | "generator" | "ai">>, selected);
    const d = await api.saveDraft(path, document, draft.revision,
                                  `accepted ${selected.length} item(s) of proposal ${proposal.id} revision ${proposal.revision}`);
    const rejected = proposal.items.filter((i) => !chosen.has(i.id)).map((i) => i.id);
    await architect.decide(path, proposal.id, proposal.revision ?? 1, selected.map((i) => i.id), rejected, "reviewed in Studio");
    setDraft(d); setValidation(d.validation);
    setSaved(`Draft revision ${d.revision} saved. It is not active: the engine still runs ${d.active.ref}.`);
    setProposal({ ...proposal, items: [] }); setChosen(new Set());
  });

  const simulate = (next: SimulatedDecision[]) => run(async () => {
    setDecisions(next);
    setSimulation(await architect.simulate(path, confirmed, next));
  });

  const assess = () => run(async () => { setReadiness(await api.readiness(workspace, useCase.id, "pilot", subject)); });

  // what readiness can be assessed for: the saved draft, a release waiting to be activated, what runs now
  useEffect(() => {
    if (step !== READINESS) return;
    void run(async () => { const [rel, d] = await Promise.all([api.releases(workspace, useCase.id), api.draft(path)]); setReleases(rel); setDraft(d); });
  }, [step, run, workspace, useCase.id, path]);
  const waiting = (releases?.items ?? []).filter((r) => r.status === "proposed" || r.status === "approved").slice(-1)[0];

  const counts = countByKind(proposal?.items ?? []);
  const hasModel = Object.keys(confirmed.entities ?? {}).length > 0;

  return (
    <div className="onboarding" data-testid="onboarding">
      <ol className="steps" aria-label="Onboarding steps">
        {STEPS.map((label, i) => (
          <li key={label}>
            <button type="button" aria-current={step === i ? "step" : undefined} onClick={() => setStep(i)}>
              <span className="num" aria-hidden="true">{i + 1}</span> {label}</button>
          </li>
        ))}
      </ol>
      <p className="notice small" role="note" data-testid="sandbox-notice">
        Sandbox only. {status?.configured
          ? (status.language_model ? "A language model answers through the engine's AI gateway."
            : "The proposals come from the sandbox architect, a deterministic test double built on approved templates: not a language model.")
          : "This use case has no architect provider: proposals are unavailable here."}{" "}
        Nothing on this screen changes what runs, grants a permission or calls another system.
      </p>
      {error && <p className="error" role="alert" data-testid="onboarding-error">{error}</p>}

      {step === 0 && (
        <section aria-labelledby="ob-describe">
          <h3 id="ob-describe">1. Describe the business</h3>
          <label htmlFor="ob-brief">Who asks for what, who decides, what is delivered</label>
          <textarea id="ob-brief" rows={5} maxLength={4000} value={brief} onChange={(e) => setBrief(e.target.value)} />
          <div className="row">
            <button type="button" className="primary" disabled={busy || !admin || !status?.configured || !brief.trim()}
                    onClick={propose}>Propose a solution</button>
            {!admin && <span className="muted small">Only someone who may configure this use case can ask for a proposal.</span>}
          </div>
        </section>
      )}

      {step === 1 && (
        <section aria-labelledby="ob-questions">
          <h3 id="ob-questions">2. Questions</h3>
          {!proposal ? <p className="muted">Describe the business first.</p> : (
            <>
              <p className="small"><span className="badge" data-testid="generator">{generatorLabel(proposal)}</span>{" "}
                Proposal {proposal.id}, revision {proposal.revision}. {proposal.items.length} provisional item(s).</p>
              {proposal.questions?.length ? (
                <form className="questions-form" onSubmit={(e) => { e.preventDefault(); void revise(); }}>
                  {proposal.questions.map((q) => (
                    <div key={q.id} className="question">
                      <label htmlFor={`q-${q.id}`}>{q.question}</label>
                      <input id={`q-${q.id}`} value={answers[q.id] ?? ""} disabled={!admin}
                             onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })} />
                      <div className="muted small">{q.why}</div>
                    </div>
                  ))}
                  <div className="row">
                    <button type="submit" className="primary" disabled={busy || !admin}>Update the proposal with my answers</button>
                    <button type="button" onClick={() => setStep(2)}>Skip: review with the assumptions</button>
                  </div>
                </form>
              ) : <p className="ok small" data-testid="no-questions">No open question: every parameter has an answer.
                  {" "}<button type="button" className="link" onClick={() => setStep(2)}>Review the proposal</button></p>}
              {(proposal.history?.length ?? 0) > 1 && (
                <p className="muted small" data-testid="history">Revisions kept: {proposal.history!.map((h) =>
                  `${h.revision} (${h.open_questions} open question(s))`).join(", ")}</p>)}
            </>
          )}
        </section>
      )}

      {step === 2 && (
        <section aria-labelledby="ob-review">
          <h3 id="ob-review">3. Review the proposed solution</h3>
          {!proposal ? <p className="muted">Describe the business first.</p> : (
            <>
              <p className="small" data-testid="review-summary">
                <span className="badge">{generatorLabel(proposal)}</span>{" "}
                {Object.entries(counts).map(([k, n]) => `${n} ${k}`).join(", ") || "nothing left to review"}.{" "}
                <span className="legend"><span className="swatch proposed" aria-hidden="true" /> proposed{" "}
                  <span className="swatch confirmed" aria-hidden="true" /> confirmed in the draft</span></p>
              <div className="canvas onboarding-canvas" data-testid="onboarding-canvas" aria-label="Proposed model graph">
                <ReactFlow key={nodes.length} nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: 0.2 }} minZoom={0.2}
                           nodesConnectable={false} elementsSelectable={false}>
                  <Background /><Controls showInteractive={false} />
                </ReactFlow>
              </div>
              <div className="review-grid">
                <div>
                  <h4>Workflow</h4>
                  <table className="small" data-testid="workflow">
                    <thead><tr><th scope="col">Entity</th><th scope="col">From → to</th><th scope="col">Action</th><th scope="col">Decided by</th></tr></thead>
                    <tbody>{flow.map((t) => (
                      <tr key={`${t.entity}-${t.action}`}><td>{t.entity}</td><td>{t.from} → {t.to}</td><td>{t.action}
                        {t.conditions.length > 0 && <div className="muted">{t.conditions.join("; ")}</div>}</td><td>{t.decidedBy}</td></tr>))}
                      {!flow.length && <tr><td colSpan={4} className="muted">No action changes a state yet.</td></tr>}</tbody>
                  </table>
                  <h4>Rules and permissions</h4>
                  <ul className="small" data-testid="access-lines">
                    {access.map((l) => <li key={l.rule}><code>{l.rule}</code> {l.text}</li>)}
                    {!access.length && <li className="muted">No rule yet.</li>}
                  </ul>
                  {proposal.suggestions && (
                    <>
                      <h4>Roles, agents and integrations (descriptions)</h4>
                      <ul className="small" data-testid="suggestions">
                        {(proposal.suggestions.roles as any[]).map((r) => <li key={`role-${r.name}`}><strong>role {r.name}</strong>: {r.description}</li>)}
                        {(proposal.suggestions.agents as any[]).map((a) => <li key={`agent-${a.name}`}><strong>agent {a.name}</strong>: {a.description}</li>)}
                        {(proposal.suggestions.integrations as any[]).map((s) => (
                          <li key={`int-${s.capability}`}><strong>{s.capability}</strong>{s.system ? ` → ${s.system}` : " → system not chosen"}: {s.description}</li>))}
                      </ul>
                      <p className="muted small">{proposal.suggestions.note}.</p>
                    </>
                  )}
                </div>
                <div>
                  <h4>Proposed items</h4>
                  <ul className="items small" data-testid="proposed-items">
                    {proposal.items.map((i) => (
                      <li key={i.id} className="provisional-item">
                        <label><input type="checkbox" checked={chosen.has(i.id)} disabled={!admin} onChange={(e) => {
                          const next = new Set(chosen); if (e.target.checked) next.add(i.id); else next.delete(i.id); setChosen(next);
                        }} /> <span className="kind">{i.kind}</span> {itemLabel(i)}{" "}
                          <span className="badge">proposed</span>{typeof i.confidence === "number" && <span className="muted"> · confidence {i.confidence}</span>}</label>
                        <div className="muted">{i.rationale}</div>
                        {(i.attention ?? []).map((a) => <div key={a} className="warn-text">{a}</div>)}
                      </li>
                    ))}
                    {!proposal.items.length && <li className="muted">Nothing is waiting for review.</li>}
                  </ul>
                  {(proposal.rejected?.length ?? 0) > 0 && (
                    <>
                      <h4>Refused by the engine</h4>
                      <ul className="small">{proposal.rejected!.map((r) => <li key={`${r.kind}-${r.name}`}><span className="kind">{r.kind}</span> {r.name}: {r.problem}</li>)}</ul>
                    </>
                  )}
                  <h4>Assumptions and unknowns</h4>
                  <ul className="small" data-testid="assumptions">
                    {(proposal.assumptions ?? []).map((a, i) => <li key={`a${i}`}>{a.statement} <span className="muted">(confidence {a.confidence})</span></li>)}
                    {(proposal.unknowns ?? []).map((u, i) => <li key={`u${i}`} className="muted">Unknown: {u}</li>)}
                  </ul>
                </div>
              </div>
              <div className="row">
                <button type="button" className="primary" disabled={busy || !selected.length} onClick={validate}>
                  Validate my selection with the engine</button>
              </div>
            </>
          )}
        </section>
      )}

      {step === 3 && (
        <section aria-labelledby="ob-confirm">
          <h3 id="ob-confirm">4. Confirm into the draft</h3>
          {saved && <p className="ok" role="status" data-testid="saved">{saved}</p>}
          {validation && (validation.valid
            ? <p className="ok small" data-testid="engine-validation">The engine's strict loader accepts this model
                ({validation.summary?.entities} entities, {validation.summary?.relationships} relationships,
                {" "}{validation.summary?.actions} actions, {validation.summary?.rules} rules).</p>
            : <ul className="error small" data-testid="engine-validation">{validation.problems.map((p, i) => <li key={i}>{p.path || "model"}: {p.message}</li>)}</ul>)}
          {!validation && !saved && <p className="muted">Review the proposal and validate your selection first.</p>}
          {validation?.valid && !saved && (
            <div className="row">
              <button type="button" className="primary" disabled={busy || !admin || !selected.length} onClick={save}>
                Save {selected.length} item(s) as a draft</button>
              <span className="muted small">A draft is not active. It becomes what runs only through a release that another person approves.</span>
            </div>
          )}
          {saved && <div className="row">
            <button type="button" className="primary" onClick={() => setStep(AGENTS)}>Configure agents and tools</button>
            <button type="button" onClick={() => setStep(DRY_RUN)}>Simulate the draft</button></div>}
        </section>
      )}

      {step === AGENTS && (
        <section aria-labelledby="ob-agents">
          <h3 id="ob-agents">5. Agents and simulated tools</h3>
          <p className="muted small">Who does the work the model describes, and with which simulated tools. Start from the suggestion,
            adjust it, and save it into the draft: the engine validates every change.</p>
          <AgentsView key={useCase.id} path={path} admin={admin} proposal={proposal?.id ?? stored}
                      onSaved={() => { void api.draft(path).then(setDraft); }} />
          <div className="row">
            <button type="button" onClick={() => setStep(DRY_RUN)}>Dry run of the draft</button>
            <button type="button" className="primary" onClick={() => setStep(RELEASE)}>Go to release</button>
          </div>
        </section>
      )}

      {step === DRY_RUN && (
        <section aria-labelledby="ob-simulate">
          <h3 id="ob-simulate">6. Dry run of the draft</h3>
          <p className="muted small">The engine's planner and rules run one synthetic case of the draft with stub tools.
            Nothing is stored and no other system is called. A stored run comes after the release.</p>
          <div className="row">
            <button type="button" className="primary" disabled={busy || !admin || !hasModel} onClick={() => simulate([])}>
              {simulation ? "Simulate again from the start" : "Run the simulation"}</button>
            {!hasModel && <span className="muted small">Save a draft first.</span>}
          </div>
          {simulation && (
            <div data-testid="simulation">
              <p><span className={`pill ${simulation.status === "completed" ? "okpill" : "warnpill"}`} data-testid="simulation-status">{simulation.status}</span>{" "}
                <span className="muted small">goal {simulation.goal} · agent roles {simulation.agent.roles.join(", ") || "none"}</span></p>
              <ol className="timeline small" data-testid="simulation-steps">
                {simulation.steps.map((s) => (
                  <li key={s.index}><strong>{s.action}</strong> — {s.outcome ?? s.verdict}
                    <span className="muted"> · {s.tool ?? "no tool"}{s.reviewer ? ` · decided by ${s.reviewer}` : ""}</span></li>))}
                {!simulation.steps.length && <li className="muted">No step was taken.</li>}
              </ol>
              {simulation.pending_review && (
                <div className="card" data-testid="pending-review">
                  <strong>{simulation.pending_review.action}</strong> waits for a decision by {simulation.pending_review.reviewers.join(" or ")}.
                  <div className="muted small">{simulation.pending_review.reasons.join("; ")} ({simulation.pending_review.rules.join(", ")})</div>
                  <div className="row">
                    {simulation.pending_review.reviewers.map((role) => (
                      <button key={role} type="button" className="primary" disabled={busy || !admin}
                              onClick={() => simulate([...decisions, { action: simulation.pending_review!.action, approved: true, as: role }])}>
                        Approve as {role} (simulated)</button>))}
                    <button type="button" disabled={busy || !admin}
                            onClick={() => simulate([...decisions, { action: simulation.pending_review!.action, approved: false,
                                                                    as: simulation.pending_review!.reviewers[0] }])}>
                      Reject (simulated)</button>
                  </div>
                </div>
              )}
              {simulation.escalation && <p className="warn small">Stopped: {simulation.escalation.reason}. {(simulation.escalation.details ?? []).join("; ")}</p>}
              {simulation.reviews.length > 0 && <p className="muted small" data-testid="simulated-reviews">
                {simulation.reviews.map((r) => `${r.action}: ${r.approved ? "approved" : "rejected"} as ${r.as} — ${r.note}`).join(" · ")}</p>}
              <details>
                <summary>Audit trace ({simulation.audit.events.length} events)</summary>
                <p className="muted small">{simulation.audit.note}.</p>
                <ol className="small audit" data-testid="audit-events">
                  {simulation.audit.events.map((e) => <li key={e.seq}><code>{e.event}</code>{" "}
                    <span className="muted">{String((e.data as any).action ?? (e.data as any).goal ?? "")}</span></li>)}
                </ol>
              </details>
              <p className="notice small">{simulation.notice}</p>
            </div>
          )}
        </section>
      )}

      {step === RELEASE && (
        <section aria-labelledby="ob-release">
          <h3 id="ob-release">7. Release and activation</h3>
          <p className="muted small">A draft becomes what runs in four governed steps, never by one person alone: another person publishes
            the draft; a release of it is proposed; another person approves it; an administrator activates it. Then the use case is
            moved to Simulation.</p>
          <ReleasesView workspace={workspace} useCase={useCase} member={member} admin={admin} onChanged={onChanged} />
          <StageOverview workspace={workspace} useCase={useCase} admin={admin} onChanged={onChanged} />
          <div className="row"><button type="button" className="primary" onClick={() => setStep(RUNS)}>Go to stored runs</button></div>
        </section>
      )}

      {step === RUNS && (
        <section aria-labelledby="ob-runs">
          <h3 id="ob-runs">8. Stored simulation runs</h3>
          <RunsView key={`${useCase.id}-${useCase.effective_stage}`} workspace={workspace} useCase={useCase} onChanged={onChanged} />
          <div className="row"><button type="button" onClick={() => setStep(READINESS)}>Go to readiness</button></div>
        </section>
      )}

      {step === READINESS && (
        <section aria-labelledby="ob-readiness">
          <h3 id="ob-readiness">9. Readiness and audit</h3>
          <p className="muted small">Readiness is computed by the engine for one configuration at a time: what runs now, the saved draft,
            or a release waiting to be activated. A draft or a waiting release has no runs of its own, so its execution evidence is missing.</p>
          <div className="row">
            <label htmlFor="rd-subject">Assess</label>
            <select id="rd-subject" value={subject} onChange={(e) => { setSubject(e.target.value); setReadiness(null); }}>
              <option value="active">what runs now{releases?.active ? ` (release ${releases.active.number})` : ""}</option>
              {(draft?.revision ?? 0) > 0 && <option value="draft">the saved draft (revision {draft!.revision})</option>}
              {waiting && <option value={`release:${waiting.number}`}>release {waiting.number} ({waiting.status}, not active)</option>}
            </select>
            <button type="button" className="primary" disabled={busy} onClick={assess}>
              {readiness ? "Assess again" : "Assess readiness for a pilot"}</button>
          </div>
          {readiness && (
            <div data-testid="readiness">
              {readiness.subject && <p className="small" data-testid="readiness-subject">
                <span className="badge">{readiness.subject.label}</span> configuration <code>{readiness.subject.configuration.slice(0, 12)}</code>
                {" "}· model {readiness.subject.model} · <span className="muted">{readiness.subject.evaluated}</span></p>}
              <p><strong data-testid="readiness-score">{readiness.score.overall ?? "—"}</strong> / 100{" "}
                <span className={`pill ${readiness.promotion.allowed ? "okpill" : "badpill"}`} data-testid="promotion">
                  {readiness.promotion.allowed ? "promotion allowed" : "promotion blocked"}</span>{" "}
                <span className="muted small">{readiness.promotion.reason}</span></p>
              <p className="muted small" data-testid="weights-status">Weights: {readiness.score.weights_status}. {readiness.score.note}.</p>
              <table className="small" data-testid="dimensions">
                <thead><tr><th scope="col">Dimension</th><th scope="col">Score</th><th scope="col">Calculation</th><th scope="col">Missing evidence</th></tr></thead>
                <tbody>{readiness.dimensions.map((d) => (
                  <tr key={d.id}><th scope="row">{d.title}</th><td>{d.score ?? "—"}</td><td className="muted">{d.calculation}</td>
                    <td>{d.missing_evidence.join("; ") || "—"}</td></tr>))}</tbody>
              </table>
              <h4>Blockers ({readiness.gates.blockers.length})</h4>
              <ul className="small" data-testid="blockers">
                {readiness.gates.blockers.map((b) => <li key={b.id}><strong>{b.title}</strong>: {b.detail}
                  <div className="muted">{b.reason}. Next: {b.action}</div></li>)}
                {!readiness.gates.blockers.length && <li className="ok">No mandatory condition is failing.</li>}
              </ul>
              {readiness.compared_with && (
                <>
                  <h4>Differences against what runs now ({readiness.compared_with.differences.length})</h4>
                  <p className="muted small">Running: score {readiness.compared_with.score ?? "—"}, configuration{" "}
                    <code>{readiness.compared_with.configuration.slice(0, 12)}</code>.</p>
                  <ul className="small" data-testid="readiness-differences">
                    {readiness.compared_with.differences.map((d) => <li key={d.id}><strong>{d.title}</strong>: {d.active} now → {d.subject} here
                      <div className="muted">{d.detail}</div></li>)}
                    {!readiness.compared_with.differences.length && <li className="muted">No condition differs.</li>}
                  </ul>
                </>
              )}
              <p className="notice small" data-testid="production">Production: not authorised. {readiness.production.reason}.</p>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
