"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, ReactFlow, type Connection, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, ApiError } from "@/lib/api";
import { ontologyToGraph } from "@/lib/graph";
import { addEntity, addRelationship, applyItems, ATTRIBUTE_TYPES, diffDocs, documentToSummary, removeAttribute,
         removeEntity, removeRelationship, setAttribute, setEntityField, setLayout, updateRelationship } from "@/lib/model";
import type { Draft, ModelDocument, Proposal, Question, Validation } from "@/lib/types";

const CARDINALITIES = ["1", "0..1", "1..*", "0..*"];
// a hint, never a default: Studio holds no domain of its own, so an empty description proposes nothing
const HINT = "Describe the process in your own words: who asks for what, who decides, and what is delivered.";

export default function DesignView({ path, admin }: { path: string; admin: boolean }) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState<ModelDocument>({});
  const [doc, setDoc] = useState<ModelDocument>({});
  const [validation, setValidation] = useState<Validation | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [edge, setEdge] = useState<number | null>(null);
  const [brief, setBrief] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  const [conflict, setConflict] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);  // a change is waiting for the engine's verdict
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    setError(""); setConflict(null);
    try {
      const d = await api.draft(path);
      setDraft(d); setSaved(d.document); setDoc(d.document); setValidation(d.validation); setQuestions(d.questions);
    } catch (e) { setError((e as Error).message); }
  }, [path]);
  useEffect(() => { void load(); }, [load]);

  const changes = useMemo(() => diffDocs(saved, doc), [saved, doc]);
  const dirty = JSON.stringify(saved) !== JSON.stringify(doc);

  // every change is validated by the engine (debounced); the UI never decides validity itself
  useEffect(() => {
    if (!draft || !dirty) return;
    setChecking(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try { const r = await api.validate(path, doc); setValidation(r.validation); setQuestions(r.questions); }
      catch (e) { setError((e as Error).message); }
      finally { setChecking(false); }
    }, 400);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [doc, draft, dirty, path]);

  const edit = (next: ModelDocument) => { if (admin) { setDoc(next); setMessage(""); } };

  // canvas: a projection of the working document
  const summary = useMemo(() => documentToSummary(doc), [doc]);
  const layout = (doc["x-studio"]?.layout ?? {}) as Record<string, { x: number; y: number }>;
  const problemNodes = new Set((validation?.problems ?? []).map((p) => p.node).filter(Boolean));
  const problemEdges = new Set((validation?.problems ?? []).map((p) => p.edge).filter((e) => e !== undefined));
  const nodes: Node[] = ontologyToGraph(summary).nodes.map((n) => ({
    id: n.id, position: layout[n.id] ?? n.position, selected: n.id === selected, draggable: admin,
    className: [saved.entities?.[n.id] ? "" : "provisional", problemNodes.has(n.id) ? "problem" : ""].join(" "),
    data: { label: `${n.id} · ${n.data.attributes} attr.${saved.entities?.[n.id] ? "" : " · new"}` },
    ariaLabel: `Entity ${n.id}${problemNodes.has(n.id) ? ", has a problem" : ""}`,
  }));
  const names = new Set(Object.keys(summary.entities));
  const edges: Edge[] = (doc.relationships ?? []).map((r: any, i: number) => ({ r, i }))
    .filter(({ r }: any) => names.has(r.from) && names.has(r.to))
    .map(({ r, i }: any) => ({ id: `r${i}`, source: r.from, target: r.to, label: `${r.type} (${r.cardinality ?? "1..*"})`,
      selected: edge === i, className: problemEdges.has(i) ? "problem" : "", labelStyle: { fontSize: 11 } }));

  function positions(): Record<string, { x: number; y: number }> {
    return Object.fromEntries(nodes.map((n) => [n.id, n.position]));
  }

  async function runProposal() {
    setError("");
    try {
      const p = await api.propose(path, brief, doc);
      setProposal(p); setChosen(new Set(p.items.map((i) => i.id)));
    } catch (e) { setError((e as Error).message); }
  }

  function accept() {
    if (!proposal) return;
    const items = proposal.items.filter((i) => chosen.has(i.id));
    edit(applyItems(doc, items));
    setProposal({ ...proposal, items: proposal.items.filter((i) => !chosen.has(i.id)) });
    setMessage(`${items.length} proposal item(s) added to your working copy — not saved, not active`);
  }

  function reject() {
    if (!proposal) return;
    setProposal({ ...proposal, items: proposal.items.filter((i) => !chosen.has(i.id)) });
  }

  async function save() {
    if (!draft) return;
    setError(""); setConflict(null);
    try {
      const d = await api.saveDraft(path, doc, draft.revision, note || "saved from Studio");
      setDraft(d); setSaved(d.document); setDoc(d.document); setValidation(d.validation); setQuestions(d.questions);
      setNote(""); setMessage(`Draft revision ${d.revision} saved. The engine still runs ${d.active.ref}.`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(Number(e.data.revision ?? 0));
      else setError((e as Error).message);
    }
  }

  function focusProblem(node?: string, edgeIndex?: number) {
    if (node) { setSelected(node); setEdge(null); }
    if (edgeIndex !== undefined) { setEdge(edgeIndex); setSelected(null); }
  }

  if (error && !draft) return <p className="error" role="alert">{error}</p>;
  if (!draft) return <p className="muted" aria-busy="true">Loading the draft…</p>;

  const ent = selected ? doc.entities?.[selected] : null;
  const rel = edge !== null ? doc.relationships?.[edge] : null;

  return (
    <div className="design">
      <div className="design-bar" role="status">
        <strong>Draft revision {draft.revision}</strong>
        <span className={dirty ? "pill warnpill" : "pill"}>{dirty ? `${changes.length} unsaved change(s)` : "saved"}</span>
        <span className={checking ? "pill" : validation?.valid ? "pill okpill" : "pill badpill"} data-testid="validity"
              aria-busy={checking}>
          {checking ? "checking with the engine…" : validation?.valid ? "valid (engine)" : "invalid (engine)"}</span>
        <span className="muted small">Not active: the engine keeps running {draft.active.ref}. Activation needs releases (planned).</span>
      </div>
      {conflict !== null && (
        <p className="warn" role="alert">Someone saved revision {conflict} while you were editing. Your changes were not saved.{" "}
          <button type="button" onClick={load}>Reload revision {conflict} (discards your unsaved changes)</button></p>
      )}
      {message && <p className="muted small" role="status">{message}</p>}
      {error && <p className="error" role="alert">{error}</p>}

      <div className="design-body">
        <section className="architect" aria-labelledby="arch-title">
          <h3 id="arch-title">Architect</h3>
          <label htmlFor="brief">Describe the business</label>
          <textarea id="brief" rows={4} value={brief} placeholder={HINT} onChange={(e) => setBrief(e.target.value)} />
          <button type="button" onClick={runProposal} disabled={!admin || !brief.trim()}>Propose</button>
          {proposal && (
            <div className="proposal" aria-label="Proposal">
              <p className="small"><span className="badge">{proposal.ai ? "AI" : "blueprint · not AI"}</span> {proposal.message}</p>
              <ul className="items">
                {proposal.items.map((i) => (
                  <li key={i.id} className="provisional-item">
                    <label>
                      <input type="checkbox" checked={chosen.has(i.id)} onChange={(e) => {
                        const next = new Set(chosen); if (e.target.checked) next.add(i.id); else next.delete(i.id); setChosen(next);
                      }} />{" "}
                      <span className="kind">{i.kind}</span> {i.name ?? (i.kind === "relationship"
                        ? `${i.value.from} —${i.value.type}→ ${i.value.to}` : i.value.id)}
                    </label>
                    <div className="muted small">{i.rationale}</div>
                  </li>
                ))}
              </ul>
              {proposal.items.length > 0 && <div className="row">
                <button type="button" className="primary" onClick={accept} disabled={!chosen.size}>Accept selected</button>
                <button type="button" onClick={reject} disabled={!chosen.size}>Reject selected</button>
              </div>}
            </div>
          )}
          <h3>Questions</h3>
          <p className="muted small">Derived by the engine from gaps in this model (rule-based).</p>
          <ul className="questions">
            {questions.map((q) => (
              <li key={q.id}>
                <button type="button" className="link" onClick={() => focusProblem(q.node)}>
                  <span className={`sev sev-${q.severity}`}>{q.severity}</span> {q.question}</button>
                <div className="muted small">{q.why}. Evidence: {q.evidence}.</div>
              </li>
            ))}
            {!questions.length && <li className="muted small">No open question.</li>}
          </ul>
        </section>

        <div className="canvas design-canvas" data-testid="design-canvas" aria-label="Draft model graph">
          {/* re-mounted when entities are added or removed, so the view fits the whole model again */}
          <ReactFlow key={nodes.length} nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.2}
                     nodesConnectable={admin} edgesFocusable
                     onNodeClick={(_, n) => { setSelected(n.id); setEdge(null); }}
                     onEdgeClick={(_, e) => { setEdge(Number(e.id.slice(1))); setSelected(null); }}
                     onNodeDragStop={(_, n) => edit(setLayout(doc, { ...positions(), [n.id]: n.position }))}
                     onConnect={(c: Connection) => {
                       if (!c.source || !c.target) return;
                       const next = addRelationship(doc, c.source, c.target);
                       edit(next); setEdge((next.relationships ?? []).length - 1); setSelected(null);
                     }}>
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>

        <aside className="inspector" aria-label="Inspector">
          {admin && (
            <form className="row" onSubmit={(e) => {
              e.preventDefault();
              const name = String(new FormData(e.currentTarget).get("entity") ?? "").trim();
              if (name) { edit(addEntity(doc, name)); setSelected(name); e.currentTarget.reset(); }
            }}>
              <label className="sr-only" htmlFor="new-entity">New entity</label>
              <input id="new-entity" name="entity" placeholder="New entity" pattern="[A-Za-z][A-Za-z0-9_]*" />
              <button type="submit">Add</button>
            </form>
          )}
          {ent && selected && (
            <div data-testid="entity-inspector">
              <h3>{selected}{!saved.entities?.[selected] && <span className="badge"> new</span>}</h3>
              {(validation?.problems ?? []).filter((p) => p.node === selected).map((p, i) => (
                <p key={i} className="error small" role="alert">{p.message}</p>
              ))}
              <label htmlFor="e-desc">Description</label>
              <input id="e-desc" value={ent.description ?? ""} disabled={!admin}
                     onChange={(e) => edit(setEntityField(doc, selected, "description", e.target.value))} />
              <label htmlFor="e-states">States (comma-separated)</label>
              <input id="e-states" value={(ent.states ?? []).join(", ")} disabled={!admin}
                     onChange={(e) => edit(setEntityField(doc, selected, "states", e.target.value))} />
              <h4>Attributes</h4>
              <table>
                <tbody>
                  {Object.entries<any>(ent.attributes ?? {}).map(([a, spec]) => (
                    <tr key={a}>
                      <th scope="row">{a}</th>
                      <td>
                        <label className="sr-only" htmlFor={`t-${a}`}>Type of {a}</label>
                        <select id={`t-${a}`} value={typeof spec === "string" ? spec : spec?.type ?? "string"} disabled={!admin}
                                onChange={(e) => edit(setAttribute(doc, selected, a, e.target.value))}>
                          {[...new Set([...(ATTRIBUTE_TYPES), typeof spec === "string" ? spec : spec?.type ?? "string"])].map((t) =>
                            <option key={t} value={t}>{t}</option>)}
                        </select>
                      </td>
                      <td>{admin && <button type="button" className="link" aria-label={`Remove ${a}`}
                                             onClick={() => edit(removeAttribute(doc, selected, a))}>×</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {admin && (
                <form className="row" onSubmit={(e) => {
                  e.preventDefault();
                  const f = new FormData(e.currentTarget);
                  const name = String(f.get("attr") ?? "").trim();
                  if (name) { edit(setAttribute(doc, selected, name, String(f.get("type")))); e.currentTarget.reset(); }
                }}>
                  <label className="sr-only" htmlFor="new-attr">New attribute</label>
                  <input id="new-attr" name="attr" placeholder="attribute" />
                  <label className="sr-only" htmlFor="new-attr-type">Type</label>
                  <input id="new-attr-type" name="type" list="attr-types" defaultValue="string" />
                  <datalist id="attr-types">{ATTRIBUTE_TYPES.map((t) => <option key={t} value={t} />)}</datalist>
                  <button type="submit">Add</button>
                </form>
              )}
              {admin && <button type="button" className="danger" onClick={() => { edit(removeEntity(doc, selected)); setSelected(null); }}>
                Remove {selected}</button>}
            </div>
          )}
          {rel && edge !== null && (
            <div data-testid="edge-inspector">
              <h3>{rel.from} → {rel.to}</h3>
              {(validation?.problems ?? []).filter((p) => p.edge === edge).map((p, i) => (
                <p key={i} className="error small" role="alert">{p.message}</p>
              ))}
              <label htmlFor="r-type">Relationship</label>
              <input id="r-type" value={rel.type ?? ""} disabled={!admin}
                     onChange={(e) => edit(updateRelationship(doc, edge, { type: e.target.value }))} />
              <label htmlFor="r-card">Cardinality</label>
              <select id="r-card" value={rel.cardinality ?? "1..*"} disabled={!admin}
                      onChange={(e) => edit(updateRelationship(doc, edge, { cardinality: e.target.value }))}>
                {CARDINALITIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              {admin && <button type="button" className="danger" onClick={() => { edit(removeRelationship(doc, edge)); setEdge(null); }}>
                Remove relationship</button>}
            </div>
          )}
          {!ent && !rel && <p className="muted small">Select an entity or a relationship. Connect two entities on the canvas to add a relationship.</p>}
        </aside>
      </div>

      <div className="design-foot">
        <section aria-labelledby="problems-title">
          <h3 id="problems-title">Validation (engine)</h3>
          {validation?.valid ? <p className="small ok">The engine's strict loader accepts this model
            ({validation.summary?.entities} entities, {validation.summary?.relationships} relationships).</p> : (
            <ul className="small">
              {(validation?.problems ?? []).map((p, i) => (
                <li key={i}><button type="button" className="link" onClick={() => focusProblem(p.node, p.edge)}>
                  {p.path || "model"}</button>: {p.message}</li>
              ))}
              {validation?.note && <li className="muted">{validation.note}</li>}
            </ul>
          )}
        </section>
        <section aria-labelledby="diff-title">
          <h3 id="diff-title">Changes since revision {draft.revision}</h3>
          <ul className="small" data-testid="diff">
            {changes.map((c, i) => <li key={i}><span className={`chg chg-${c.change}`}>{c.change}</span> {c.kind} {c.label}</li>)}
            {!changes.length && <li className="muted">None.</li>}
          </ul>
          {admin && (
            <div className="row">
              <label className="sr-only" htmlFor="save-note">Note</label>
              <input id="save-note" placeholder="What changed (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
              <button type="button" className="primary" onClick={save} disabled={!dirty}>Save draft</button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
