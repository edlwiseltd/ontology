"use client";

// Synthetic simulation records of a use case in Draft or Simulation: listed, created and changed through the engine's
// own record API. Studio decides nothing here. The engine checks the data administration permission, each field's
// write rule (a decision-critical fact binds every writer), the record's revision (no lost update), validates the
// values against the model, and records each write. A refusal is shown as the engine worded it.

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, runs as engine } from "@/lib/api";
import { changes, editable, fieldsOf, fromForm, toForm, validId, type EntitySpec } from "@/lib/records";
import type { EngineMe, ObjectRow } from "@/lib/runs";

export default function RecordEditor({ path, stage, me, entities, onChanged }: {
  path: string; stage: string; me: EngineMe | null; entities: Record<string, EntitySpec>; onChanged?: () => void }) {
  const names = useMemo(() => Object.keys(entities).sort(), [entities]);
  const [type, setType] = useState("");
  const [rows, setRows] = useState<ObjectRow[]>([]);
  const [editing, setEditing] = useState<ObjectRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [newId, setNewId] = useState("");
  const [form, setForm] = useState<Record<string, string | boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const fields = useMemo(() => fieldsOf(entities[type]), [entities, type]);
  const gate = editable(stage);
  const mayWrite = !!me && me.permissions.includes("admin");
  const mayRead = !!me && (me.permissions.includes("read") || me.permissions.includes("admin"));
  useEffect(() => { setType((cur) => (names.includes(cur) ? cur : names[0] ?? "")); }, [names]);

  const load = useCallback(async () => {
    if (!type || !mayRead) { setRows([]); return; }
    try { setRows((await engine.objects(path, type)).items); } catch (e) { setError((e as Error).message); }
  }, [path, type, mayRead]);
  useEffect(() => { void load(); setEditing(null); setCreating(false); setError(""); setMessage(""); }, [load]);

  function open(row: ObjectRow | null) {
    setEditing(row); setCreating(row === null); setNewId(""); setForm(toForm(fields, row)); setError(""); setMessage("");
  }

  const draft = fromForm(fields, form);
  const pending = draft.attributes ? changes(editing, draft.attributes) : [];

  async function save() {
    if (!draft.attributes) { setError(draft.problems.join("; ")); return; }
    const id = editing?.id ?? newId.trim();
    if (!validId(id)) { setError("Give the record an identifier: letters, digits, dot, dash, underscore or colon."); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      // expected_revision: the revision that was read (0: the record must not exist yet). The engine refuses a stale write
      const saved = await engine.upsert(path, { type, id, attributes: draft.attributes, expected_revision: editing?.revision ?? 0,
                                               justification: "synthetic simulation record edited in Studio" });
      setMessage(`${saved.id} saved at revision ${saved.revision}. The engine checked your permission, the write rules and the model.`);
      setEditing(null); setCreating(false);
      await load(); onChanged?.();
    } catch (e) { setError(e instanceof ApiError ? e.message : (e as Error).message); }
    finally { setBusy(false); }
  }

  if (!names.length || !mayRead) return null;
  return (
    <section className="card" aria-labelledby="records-title" data-testid="record-editor">
      <div className="row spread">
        <h3 id="records-title">Synthetic records</h3>
        <button type="button" className="small" onClick={() => void load()}>Refresh</button>
      </div>
      <p className="muted small" data-testid="records-note">Invented data for simulation: never a real customer, person or contract. {gate.why}{" "}
        {gate.allowed && (mayWrite ? "The engine checks each change (your permission, the field's write rule, the record's revision) and records it."
          : "You may read them. Changing a record needs the data administration permission on this use case, which two people grant (Access).")}</p>
      <div className="row">
        <label htmlFor="records-type">Entity</label>
        <select id="records-type" value={type} onChange={(e) => setType(e.target.value)}>
          {names.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        {gate.allowed && mayWrite && <button type="button" onClick={() => open(null)} data-testid="record-new">New {type}</button>}
      </div>
      <table className="small" data-testid="record-list">
        <thead><tr><th scope="col">Record</th><th scope="col">Values</th><th scope="col">Revision</th><th scope="col"><span className="sr-only">Edit</span></th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}><td><code>{r.id}</code></td>
              <td>{Object.entries(r.attributes).map(([k, v]) => `${k}: ${String(v)}`).join(" · ") || <span className="muted">no value</span>}</td>
              <td>{r.revision}</td>
              <td>{gate.allowed && mayWrite && <button type="button" className="small" onClick={() => open(r)} aria-label={`Edit ${r.id}`}>Edit</button>}</td></tr>))}
          {!rows.length && <tr><td colSpan={4} className="muted">No {type} record that you may see.</td></tr>}
        </tbody>
      </table>
      {(editing || creating) && (
        <form className="record-form" data-testid="record-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <h4>{editing ? `Edit ${editing.id} (revision ${editing.revision})` : `New ${type}`}</h4>
          {creating && (
            <div className="question"><label htmlFor="record-id">Identifier</label>
              <input id="record-id" value={newId} maxLength={80} onChange={(e) => setNewId(e.target.value)} placeholder={`${type.toUpperCase().slice(0, 4)}-1`} /></div>)}
          {fields.map((f) => (
            <div key={f.name} className="question">
              <label htmlFor={`record-${f.name}`}>{f.name} <span className="muted">({f.type})</span></label>
              {f.type === "boolean"
                ? <input id={`record-${f.name}`} type="checkbox" checked={form[f.name] === true} onChange={(e) => setForm({ ...form, [f.name]: e.target.checked })} />
                : f.type === "state"
                  ? <select id={`record-${f.name}`} value={String(form[f.name] ?? "")} onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}>
                      {(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}</select>
                  : <input id={`record-${f.name}`} value={String(form[f.name] ?? "")} inputMode={f.type === "number" || f.type === "integer" ? "decimal" : undefined}
                           onChange={(e) => setForm({ ...form, [f.name]: e.target.value })} />}
            </div>))}
          <p className="small" data-testid="record-changes">{draft.problems.length ? <span className="warn-text">{draft.problems.join("; ")}</span>
            : pending.length ? <>Will change: {pending.join("; ")}</> : "Nothing changed."}</p>
          <div className="row">
            <button type="submit" className="primary" disabled={busy || draft.problems.length > 0 || (!!editing && !pending.length)} data-testid="record-save">Save through the engine</button>
            <button type="button" onClick={() => { setEditing(null); setCreating(false); }}>Cancel</button>
          </div>
        </form>)}
      {message && <p className="ok small" role="status" data-testid="record-message">{message}</p>}
      {error && <p className="error" role="alert" data-testid="record-error">{error}</p>}
    </section>
  );
}
