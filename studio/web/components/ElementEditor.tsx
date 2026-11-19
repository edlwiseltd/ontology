"use client";

// The correction of one proposed element: the content as proposed beside the content as the person writes it.
// Submitting sends it to the engine's decision route; this component records nothing and shows no success of its own.
import { useMemo, useState } from "react";
import { changedKeys, fieldsOf, parseFields, unchanged, type EditField } from "@/lib/correction";

export default function ElementEditor({ label, original, busy, onSubmit, onCancel }: {
  label: string; original: Record<string, unknown>; busy: boolean;
  onSubmit: (value: Record<string, unknown>, note: string) => void; onCancel: () => void;
}) {
  const [fields, setFields] = useState<EditField[]>(() => fieldsOf(original));
  const [note, setNote] = useState("");
  const parsed = useMemo(() => parseFields(fields), [fields]);
  const same = unchanged(original, fields);
  const changed = parsed.value ? changedKeys(original, parsed.value) : [];
  const set = (key: string, text: string) => setFields(fields.map((f) => (f.key === key ? { ...f, text } : f)));
  return (
    <div className="card element-editor" role="group" aria-label={`Correct ${label}`} data-testid="element-editor">
      <h4>Correct {label}</h4>
      <p className="small muted">The content the architect proposed is on the left and stays on record. What you write on the right
        replaces it for the model, under your name. The engine validates it like any other element. No provider is asked.</p>
      <div className="editor-grid">
        <div>
          <h5>As proposed</h5>
          <pre className="small" data-testid="editor-original">{JSON.stringify(original, null, 1)}</pre>
        </div>
        <div>
          <h5>As you correct it</h5>
          {fields.map((f) => (
            <div key={f.key}>
              <label htmlFor={`ed-${f.key}`}>{f.key}{f.kind === "lines" ? " (one per line)" : f.kind === "pairs" ? " (one per line, name: value)"
                : f.kind === "json" ? " (structured: JSON data)" : ""}{changed.includes(f.key) ? " · changed" : ""}</label>
              {f.kind === "flag" ? (
                <select id={`ed-${f.key}`} value={f.text} onChange={(e) => set(f.key, e.target.value)}><option value="true">yes</option><option value="false">no</option></select>
              ) : f.kind === "text" && f.text.length < 80 ? (
                <input id={`ed-${f.key}`} value={f.text} maxLength={500} onChange={(e) => set(f.key, e.target.value)} />
              ) : f.kind === "number" ? (
                <input id={`ed-${f.key}`} value={f.text} inputMode="decimal" maxLength={30} onChange={(e) => set(f.key, e.target.value)} />
              ) : (
                <textarea id={`ed-${f.key}`} value={f.text} rows={Math.min(8, Math.max(2, f.text.split("\n").length))} maxLength={4000}
                          onChange={(e) => set(f.key, e.target.value)} spellCheck={false} />
              )}
            </div>))}
          <label htmlFor="ed-note">Why (kept with your correction)</label>
          <input id="ed-note" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
        </div>
      </div>
      {parsed.problems.length > 0 && <ul className="error small" role="alert" data-testid="editor-problems">{parsed.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <div className="row">
        <button type="button" className="primary" disabled={busy || same || !parsed.value} data-testid="editor-submit"
                onClick={() => parsed.value && onSubmit(parsed.value, note)}>Submit this correction to the engine</button>
        <button type="button" onClick={onCancel} data-testid="editor-cancel">Cancel</button>
        <span className="small muted" aria-live="polite">{same ? "Nothing is changed yet." : `${changed.length} part(s) changed: ${changed.join(", ")}`}</span>
      </div>
    </div>
  );
}
