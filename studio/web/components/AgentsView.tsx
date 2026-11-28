"use client";

// Agents and simulated tools of a use case's draft. Studio edits a working copy and asks; the engine validates it
// against the draft's model, says what each agent may do and stores it as a draft. Nothing saved here runs: it
// becomes active only through a release another person approves. Every assignable tool is simulated.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Background, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, configuration, ApiError } from "@/lib/api";
import { addAgent, agentGraph, listOf, reasonsOf, removeAgent, rolesIn, setTool, STATE_LABEL, STATUS_LABEL, toolOf,
         updateAgent } from "@/lib/solution";
import type { AgentSpec, ModelDocument, Solution, SolutionDraft, ToolAssignment } from "@/lib/types";

interface Props {
  path: string;
  admin: boolean;
  /** a stored proposal whose approved template may carry a starting configuration */
  proposal?: string;
  /** called after a save, with the engine's view of the draft */
  onSaved?: (view: SolutionDraft) => void;
}

export default function AgentsView({ path, admin, proposal, onSaved }: Props) {
  const [view, setView] = useState<SolutionDraft | null>(null);
  const [doc, setDoc] = useState<ModelDocument>({});
  const [working, setWorking] = useState<Solution | null>(null);
  const [agent, setAgent] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [newName, setNewName] = useState("");

  const run = useCallback(async (work: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await work(); }
    catch (e) { setError(e instanceof ApiError ? e.message : (e as Error).message); }
    finally { setBusy(false); }
  }, []);

  const show = useCallback((v: SolutionDraft, changed: boolean) => {
    setView(v); setWorking(v.solution); setDirty(changed);
    setAgent((current) => (current && v.solution?.agents[current] ? current : Object.keys(v.solution?.agents ?? {})[0] ?? null));
  }, []);

  useEffect(() => {
    void run(async () => {
      const [v, d] = await Promise.all([configuration.draft(path), api.draft(path)]);
      setDoc(d.document); show(v, false);
    });
  }, [path, run, show]);

  const editable = admin && (view?.active.editable ?? false);
  const actions = useMemo(() => Object.keys(doc.actions ?? {}).sort(), [doc]);
  const goals = useMemo(() => Object.keys(doc.goals ?? {}).sort(), [doc]);
  const roles = useMemo(() => rolesIn(doc), [doc]);
  const available = (view?.catalog ?? []).filter((c) => c.available);
  const unavailable = (view?.catalog ?? []).filter((c) => !c.available);
  const spec: AgentSpec | null = (agent && working?.agents[agent]) || null;
  const graph = useMemo(() => agentGraph(working, view?.permissions ?? {}), [working, view]);
  const nodes: Node[] = graph.nodes.map((n) => ({
    id: n.id, position: { x: n.x, y: n.y }, draggable: false, className: `flow-${n.kind} ${n.status ? `status-${n.status}` : ""}`,
    data: { label: n.kind === "agent" ? `agent · ${n.label}` : n.label }, ariaLabel: `${n.kind} ${n.label}`,
    sourcePosition: "right" as Node["sourcePosition"], targetPosition: "left" as Node["targetPosition"],
  }));
  const edges: Edge[] = graph.edges.map((e) => ({ id: e.id, source: e.source, target: e.target }));

  // every edit is checked by the engine: the working copy is never trusted to be valid
  const change = (next: Solution | null) => run(async () => {
    setWorking(next); setDirty(true); setMessage("");
    const v = await configuration.validate(path, next);
    setView({ ...v, revision: view?.revision ?? v.revision });
  });

  const edit = (c: Partial<AgentSpec>) => { if (working && agent) void change(updateAgent(working, agent, c)); };
  const assign = (action: string, tool: string, params: Partial<ToolAssignment> = {}) => {
    if (working && agent) void change(setTool(working, agent, action, tool, params));
  };

  const suggest = () => run(async () => {
    const v = await configuration.suggest(path, proposal);
    setWorking(v.solution); setView({ ...v, revision: view?.revision ?? v.revision }); setDirty(true);
    setAgent(Object.keys(v.solution?.agents ?? {})[0] ?? null);
    setMessage(`A starting configuration (${v.source === "generic" ? "one agent, every action simulated" : v.source}). It is not saved yet.`);
  });

  const save = (solution: Solution | null, note: string) => run(async () => {
    if (!view) return;
    const v = await configuration.save(path, solution, view.revision, note);
    show(v, false);
    setMessage(solution ? `Draft revision ${v.revision} saved. It does not run: publish it and activate a release to use it.`
      : `The draft configuration was withdrawn (draft revision ${v.revision}).`);
    onSaved?.(v);
  });

  if (!view) return <p className="muted" aria-busy={busy}>{error || "Loading the configuration…"}</p>;
  const problems = view.validation.problems;
  const rows = (agent && view.permissions[agent]) || [];
  const state = dirty ? (view.state === "validated" ? "Unsaved · validated by the engine" : view.state === "invalid" ? "Unsaved · not valid" : "Unsaved · empty")
    : STATE_LABEL[view.state];

  return (
    <div className="agents" data-testid="agents">
      <div className="row spread">
        <p className="small" style={{ margin: 0 }}>
          <span className={`pill ${view.state === "invalid" ? "warnpill" : "okpill"}`} data-testid="config-state">{state}</span>{" "}
          <span className="muted">Draft revision {view.revision}{view.author ? ` by ${view.author}` : ""}.</span>
        </p>
        <p className="small" style={{ margin: 0 }} data-testid="config-active">
          <span className="badge">running now</span>{" "}
          {view.active.agents.length ? `agents ${view.active.agents.join(", ")}` : "no agent"} · {view.active.note}
        </p>
      </div>
      <p className="notice small" role="note" data-testid="simulated-notice">
        Simulated only. Every tool you can assign answers from a table inside Autology and contacts no other system.
        Saving here changes nothing that runs and enables no external action.
      </p>
      {!view.active.editable && <p className="warn-text" role="status" data-testid="config-readonly">{view.active.note}.</p>}
      {!admin && <p className="muted small" role="status" data-testid="config-denied">You can read this configuration. Only someone who may configure this use case can change it.</p>}
      {error && <p className="error" role="alert" data-testid="config-error">{error}</p>}
      {message && <p className="ok small" role="status" data-testid="config-message">{message}</p>}

      <div className="agents-body">
        <section aria-labelledby="ag-list" className="agents-list">
          <h3 id="ag-list">Agents</h3>
          <ul className="uc-list" data-testid="agent-list">
            {Object.keys(working?.agents ?? {}).map((name) => (
              <li key={name}><button type="button" aria-current={name === agent ? "true" : undefined} onClick={() => setAgent(name)}>
                <span>{name}<br /><span className="muted small">{working!.agents[name].tools.length} action(s) permitted</span></span>
              </button></li>
            ))}
          </ul>
          {!Object.keys(working?.agents ?? {}).length && <p className="muted small">No agent in the draft: nothing could run from a release of it.</p>}
          {editable && (
            <form className="row" onSubmit={(e) => {
              e.preventDefault();
              const name = newName.trim();
              if (!name) return;
              setAgent(name); setNewName(""); void change(addAgent(working, name, doc));
            }}>
              <label className="sr-only" htmlFor="ag-new">New agent name</label>
              <input id="ag-new" value={newName} placeholder="new agent name" pattern="[A-Za-z_][A-Za-z0-9_\-]{0,63}"
                     onChange={(e) => setNewName(e.target.value)} />
              <button type="submit" disabled={busy}>Add agent</button>
            </form>
          )}
          {editable && <button type="button" disabled={busy || !actions.length} onClick={suggest} data-testid="suggest-config">
            Suggest a starting configuration</button>}
          {!actions.length && <p className="muted small">The draft's model has no action yet: design the model first.</p>}

          <h3>Not available here</h3>
          <ul className="small" data-testid="unavailable-tools">
            {unavailable.map((c) => <li key={c.id}><strong>{c.name}</strong> <span className="badge">unavailable</span>
              <div className="muted">{c.description}</div></li>)}
          </ul>
        </section>

        <section aria-labelledby="ag-edit" className="agents-edit">
          <h3 id="ag-edit">{agent ? `Agent ${agent}` : "Configuration"}</h3>
          {!spec || !agent ? <p className="muted">Choose or add an agent.</p> : (
            <>
              <label htmlFor="ag-purpose">Purpose</label>
              <input id="ag-purpose" defaultValue={spec.purpose ?? ""} key={`p-${agent}`} disabled={!editable} maxLength={500}
                     onBlur={(e) => e.target.value !== (spec.purpose ?? "") && edit({ purpose: e.target.value })} />
              <label htmlFor="ag-duties">Responsibilities (one per line)</label>
              <textarea id="ag-duties" rows={2} defaultValue={(spec.responsibilities ?? []).join("\n")} key={`d-${agent}`} disabled={!editable}
                        onBlur={(e) => edit({ responsibilities: e.target.value.split("\n").map((v) => v.trim()).filter(Boolean) })} />
              <label htmlFor="ag-roles">Roles the agent holds (names the rules refer to; a role grants only what a rule says)</label>
              <input id="ag-roles" defaultValue={spec.roles.join(", ")} key={`r-${agent}-${spec.roles.join()}`} disabled={!editable}
                     list="ag-roles-known" onBlur={(e) => listOf(e.target.value).join() !== spec.roles.join() && edit({ roles: listOf(e.target.value) })} />
              <datalist id="ag-roles-known">{roles.map((r) => <option key={r} value={r} />)}</datalist>
              {roles.length > 0 && <p className="muted small">Roles named by the model's rules: {roles.join(", ")}.</p>}

              <fieldset>
                <legend>Goals pursued</legend>
                {goals.map((g) => (
                  <label key={g} className="check"><input type="checkbox" checked={spec.goals.includes(g)} disabled={!editable}
                    onChange={(e) => edit({ goals: e.target.checked ? [...spec.goals, g] : spec.goals.filter((x) => x !== g) })} /> {g}</label>
                ))}
                {!goals.length && <span className="muted small">The model has no goal yet.</span>}
              </fieldset>

              <fieldset data-testid="autonomy">
                <legend>Autonomy policy</legend>
                <label className="check"><input type="radio" name={`auto-${agent}`} checked={spec.autonomy.mode === "policy"} disabled={!editable}
                  onChange={() => edit({ autonomy: { mode: "policy" } })} /> The model's rules decide: the agent acts on its own unless a rule asks for a person</label>
                <label className="check"><input type="radio" name={`auto-${agent}`} checked={spec.autonomy.mode === "supervised"} disabled={!editable}
                  onChange={() => edit({ autonomy: { mode: "supervised", reviewer: roles[0] ?? "supervisor" } })} /> Supervised: a person also decides every action that changes something</label>
                {spec.autonomy.mode === "supervised" && (
                  <>
                    <label htmlFor="ag-reviewer">Reviewer role</label>
                    <input id="ag-reviewer" defaultValue={spec.autonomy.reviewer ?? ""} key={`rv-${agent}`} disabled={!editable} list="ag-roles-known"
                           onBlur={(e) => edit({ autonomy: { ...spec.autonomy, reviewer: e.target.value.trim() } })} />
                  </>
                )}
                <p className="muted small">This setting can only add reviews. It never removes one the rules require.</p>
              </fieldset>

              <h4>Permitted actions and their simulated tools</h4>
              <table className="small" data-testid="tool-table">
                <thead><tr><th scope="col">Action</th><th scope="col">Tool (simulated)</th><th scope="col">Setting</th><th scope="col">What the agent may do</th></tr></thead>
                <tbody>
                  {actions.map((name) => {
                    const t = toolOf(spec, name);
                    const p = rows.find((r) => r.action === name);
                    const outcomes: string[] = (doc.actions?.[name]?.outcomes ?? []).map((o: any) => o.name);
                    return (
                      <tr key={name} data-action={name}>
                        <th scope="row">{name}<div className="muted">{doc.actions?.[name]?.side_effect ?? "none"}</div></th>
                        <td>
                          <label className="sr-only" htmlFor={`tool-${name}`}>Tool for {name}</label>
                          <select id={`tool-${name}`} value={t?.tool ?? ""} disabled={!editable}
                                  onChange={(e) => assign(name, e.target.value, e.target.value === "simulated.decision_table"
                                    ? { rows: [{ outcome: outcomes[0], message: "" }] } : {})}>
                            <option value="">not permitted</option>
                            {available.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                            {unavailable.map((c) => <option key={c.id} value={c.id} disabled>{c.name} (unavailable)</option>)}
                          </select>
                        </td>
                        <td>
                          {t?.tool === "simulated.succeed" && outcomes.length > 1 && (
                            <>
                              <label className="sr-only" htmlFor={`out-${name}`}>Outcome of {name}</label>
                              <select id={`out-${name}`} value={t.outcome ?? ""} disabled={!editable}
                                      onChange={(e) => assign(name, t.tool, e.target.value ? { outcome: e.target.value } : {})}>
                                <option value="">expected outcome</option>
                                {outcomes.map((o) => <option key={o} value={o}>{o}</option>)}
                              </select>
                            </>
                          )}
                          {t?.tool === "simulated.fail" && (
                            <>
                              <label className="sr-only" htmlFor={`err-${name}`}>Failure message of {name}</label>
                              <input id={`err-${name}`} defaultValue={t.error ?? ""} placeholder="failure message" disabled={!editable}
                                     onBlur={(e) => assign(name, t.tool, { ...(t.when ? { when: t.when } : {}), error: e.target.value })} />
                              <label className="sr-only" htmlFor={`when-${name}`}>Only when</label>
                              <input id={`when-${name}`} defaultValue={t.when ?? ""} placeholder="only when (condition, optional)" disabled={!editable}
                                     onBlur={(e) => assign(name, t.tool, { ...(t.error ? { error: t.error } : {}), ...(e.target.value.trim() ? { when: e.target.value.trim() } : {}) })} />
                            </>
                          )}
                          {t?.tool === "simulated.decision_table" && (
                            <ol className="rows">
                              {(t.rows ?? []).map((r, i) => (
                                <li key={i}>
                                  <label className="sr-only" htmlFor={`rw-${name}-${i}`}>Row {i + 1} condition</label>
                                  <input id={`rw-${name}-${i}`} defaultValue={r.when ?? ""} placeholder="when (empty: otherwise)" disabled={!editable}
                                         onBlur={(e) => assign(name, t.tool, { rows: t.rows!.map((x, j) => j === i
                                           ? { ...x, when: e.target.value.trim() || undefined } : x) })} />
                                  <label className="sr-only" htmlFor={`ro-${name}-${i}`}>Row {i + 1} outcome</label>
                                  <select id={`ro-${name}-${i}`} value={r.outcome ?? ""} disabled={!editable}
                                          onChange={(e) => assign(name, t.tool, { rows: t.rows!.map((x, j) => j === i
                                            ? { ...x, outcome: e.target.value || undefined } : x) })}>
                                    <option value="">expected outcome</option>
                                    {outcomes.map((o) => <option key={o} value={o}>{o}</option>)}
                                  </select>
                                  {r.updates && <span className="muted"> writes {Object.entries(r.updates).map(([e, c]) =>
                                    Object.keys(c).map((a) => `${e}.${a}`).join(", ")).join(", ")}</span>}
                                </li>
                              ))}
                              {editable && (t.rows?.length ?? 0) < 20 && <li><button type="button" className="link"
                                onClick={() => assign(name, t.tool, { rows: [...(t.rows ?? []), { outcome: outcomes[0] }] })}>Add a row</button></li>}
                            </ol>
                          )}
                        </td>
                        <td data-testid={`perm-${name}`}>
                          {p ? <><span className={`pill status-${p.status}`}>{STATUS_LABEL[p.status]}</span>
                            {reasonsOf(p) && <div className="muted">{reasonsOf(p)}</div>}</> : <span className="muted">—</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {editable && <button type="button" className="link" disabled={busy} data-testid="remove-agent"
                onClick={() => { const next = removeAgent(working!, agent); setAgent(Object.keys(next.agents)[0] ?? null); void change(next); }}>
                Remove agent {agent} from the draft</button>}
            </>
          )}
        </section>
      </div>

      {graph.nodes.length > 0 && (
        <div className="canvas agents-canvas" data-testid="agents-canvas" aria-label="Agents, permitted actions and simulated tools">
          <ReactFlow key={graph.nodes.length} nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.2}
                     nodesConnectable={false} elementsSelectable={false}><Background /></ReactFlow>
        </div>
      )}

      <div className="review-grid">
        <section aria-labelledby="ag-valid">
          <h3 id="ag-valid">Engine validation</h3>
          {view.state === "none" ? <p className="muted small" data-testid="config-validation">Nothing to validate.</p>
            : problems.length === 0
              ? <p className="ok small" data-testid="config-validation">Valid ({view.validation.by}). {view.simulated_tools.length} simulated tool(s): {view.simulated_tools.join(", ") || "none"}.</p>
              : <ul className="error small" data-testid="config-validation">{problems.map((p, i) => <li key={i}><code>{p.path || "configuration"}</code>: {p.message}</li>)}</ul>}
          {(working?.sample_data?.instances?.length ?? 0) > 0 && (
            <p className="small" data-testid="sample-data">{working!.sample_data!.instances.length} synthetic sample record(s)
              ({[...new Set(working!.sample_data!.instances.map((i) => String(i.type)))].join(", ")}): loaded only into an empty store.</p>)}
        </section>
        <section aria-labelledby="ag-changes">
          <h3 id="ag-changes">Changes against what runs now</h3>
          <ul className="small" data-testid="config-changes">
            {view.changes.map((c) => <li key={`${c.kind}-${c.name}`}><span className={`chg-${c.change}`}>{c.change}</span> {c.kind} {c.name}
              {c.fields.length > 0 && <span className="muted"> ({c.fields.join(", ")})</span>}</li>)}
            {!view.changes.length && <li className="muted">No difference: the draft configuration is what runs.</li>}
          </ul>
        </section>
      </div>

      {editable && (
        <div className="row">
          <button type="button" className="primary" disabled={busy || !dirty || view.state !== "validated"} data-testid="save-config"
                  onClick={() => save(working, "configuration saved from Studio")}>Save the draft configuration</button>
          <button type="button" disabled={busy || (!dirty && view.state === "none")} data-testid="withdraw-config"
                  onClick={() => save(null, "draft configuration withdrawn")}>Withdraw the draft configuration</button>
          {dirty && view.state === "invalid" && <span className="muted small">Fix the problems above: the engine stores only a valid configuration.</span>}
        </div>
      )}
    </div>
  );
}
