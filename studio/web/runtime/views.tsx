"use client";

// The component registry of the application runtime: one component per view type of the manifest schema, and no
// other. A view shows what the Engine answers for this caller; it evaluates no rule and hides nothing for security.
// Every value is rendered as text.

import { useCallback, useEffect, useMemo, useState } from "react";
import { call, EngineError, type Caller } from "./client";
import { cell, countBy, fieldValue, filterLoaded, formProblems, formRecord, graph, linked, outcome, RUN_TEXT, runLabel, timeline, viewFor } from "./model";
import type { AuditEntry, Manifest, May, Mode, RecordRow, Review, RuleInfo, Run, View } from "./types";

export interface Ctx {
  who: Caller; manifest: Manifest; mode: Mode; may: May; rules: Record<string, RuleInfo>;
  open: (viewId: string, record?: string) => void; record?: string; say: (line: string) => void;
}
type Props = { view: View; ctx: Ctx };
interface Page { items: RecordRow[]; total?: number }

function useLoad<T>(ctx: Ctx, path: string | null, deps: unknown[]): { data: T | null; error: string; loading: boolean; reload: () => void } {
  const [state, setState] = useState<{ data: T | null; error: string; loading: boolean }>({ data: null, error: "", loading: !!path });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path || ctx.mode === "configuration") { setState({ data: null, error: "", loading: false }); return; }
    let live = true;
    setState((s) => ({ ...s, loading: true, error: "" }));
    call<T>(ctx.who, "GET", path).then((data) => { if (live) setState({ data, error: "", loading: false }); })
      .catch((e: EngineError) => { if (live) setState({ data: null, error: e.status === 404 ? "Not found, or not shown to you." : e.message, loading: false }); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ctx.mode, ...deps]);
  return { ...state, reload: useCallback(() => setTick((t) => t + 1), []) };
}

const NoData = () => <p className="muted small" data-testid="rt-no-data">A configuration preview shows the screens as designed. No record is read.</p>;
const Status = ({ value }: { value: unknown }) => <span className="rt-pill">{cell(value)}</span>;
const Busy = ({ on }: { on: boolean }) => (on ? <p className="muted small" role="status">Loading…</p> : null);
const Failed = ({ text }: { text: string }) => (text ? <p className="error" role="alert">{text}</p> : null);

// -- records ---------------------------------------------------------------------------------------------------
export function EntityList({ view, ctx }: Props) {
  const size = view.page_size ?? 25;
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const { data, error, loading } = useLoad<Page>(ctx, `/objects?type=${encodeURIComponent(view.entity ?? "")}&limit=${size}&offset=${offset}`, [view.id]);
  const columns = view.columns ?? [];
  const rows = filterLoaded(data?.items ?? [], query, columns);
  const detail = viewFor(ctx.manifest, "EntityDetailView", view.entity ?? "");
  const form = viewFor(ctx.manifest, "RecordFormView", view.entity ?? "");
  const total = data?.total ?? data?.items.length ?? 0;
  return (
    <section aria-labelledby="rt-list-title" data-testid="rt-list">
      <div className="row spread">
        <h2 id="rt-list-title">{view.title}</h2>
        {form && <button type="button" className="small" onClick={() => ctx.open(form.id)} data-testid="rt-new">New…</button>}
      </div>
      {ctx.mode === "configuration" ? <NoData /> : (
        <>
          <label htmlFor="rt-filter">Filter the records loaded on this page</label>
          <input id="rt-filter" value={query} onChange={(e) => setQuery(e.target.value)} maxLength={80} placeholder="text in any column shown" />
          <Busy on={loading} /><Failed text={error} />
        </>)}
      <div className="rt-scroll">
        <table className="rt-table" data-testid="rt-table">
          <thead><tr><th scope="col">Record</th>{columns.map((c) => <th key={c.field} scope="col">{c.label}</th>)}</tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <th scope="row">{detail ? <button type="button" className="link" onClick={() => ctx.open(detail.id, r.id)}>{r.id}</button> : r.id}</th>
                {columns.map((c) => <td key={c.field}>{c.field === "status" ? <Status value={fieldValue(r, c.field)} /> : cell(fieldValue(r, c.field))}</td>)}
              </tr>))}
          </tbody>
        </table>
      </div>
      {ctx.mode !== "configuration" && !loading && !error && rows.length === 0 && (
        <p className="muted" data-testid="rt-empty">{query ? "No loaded record contains this text." : "No record is shown to you here."}</p>)}
      {ctx.mode !== "configuration" && data && (
        <div className="row rt-pager">
          <button type="button" className="small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - size))}>Previous</button>
          <span className="small muted" data-testid="rt-count">{total === 0 ? "0 records" : `${offset + 1}–${offset + data.items.length} of ${total}`}</span>
          <button type="button" className="small" disabled={offset + size >= total} onClick={() => setOffset(offset + size)}>Next</button>
        </div>)}
    </section>
  );
}

export function EntityDetail({ view, ctx }: Props) {
  const { data, error, loading } = useLoad<RecordRow>(ctx, ctx.record ? `/objects/${encodeURIComponent(ctx.record)}` : null, [ctx.record]);
  const links = viewFor(ctx.manifest, "RelationshipView", view.entity ?? "");
  const work = viewFor(ctx.manifest, "WorkflowView", view.entity ?? "");
  const list = viewFor(ctx.manifest, "EntityListView", view.entity ?? "");
  if (ctx.mode === "configuration" || !ctx.record) {
    return (
      <section data-testid="rt-detail"><h2>{view.title}</h2>
        {ctx.mode === "configuration" ? <NoData /> : <p className="muted">Choose a record from its list.</p>}
        <dl className="rt-fields">{(view.fields ?? []).map((f) => <div key={f.field}><dt>{f.label}</dt><dd className="muted">—</dd></div>)}</dl>
        {(view.related ?? []).map((r) => <h3 key={r.relationship + r.direction + r.entity}>{r.label}</h3>)}
      </section>);
  }
  return (
    <section aria-labelledby="rt-detail-title" data-testid="rt-detail">
      <div className="row spread">
        <h2 id="rt-detail-title">{view.title} <span className="muted">{ctx.record}</span></h2>
        <span className="row">
          {list && <button type="button" className="small" onClick={() => ctx.open(list.id)}>Back to the list</button>}
          {links && <button type="button" className="small" onClick={() => ctx.open(links.id, ctx.record)} data-testid="rt-open-links">Relationships</button>}
          {work && <button type="button" className="small primary" onClick={() => ctx.open(work.id, ctx.record)} data-testid="rt-open-work">Work on this record</button>}
        </span>
      </div>
      <Busy on={loading} /><Failed text={error} />
      {data && (
        <>
          <dl className="rt-fields" data-testid="rt-fields">
            {(view.fields ?? []).map((f) => (
              <div key={f.field}><dt>{f.label}</dt>
                <dd>{f.field === "status" ? <Status value={fieldValue(data, f.field)} /> : cell(fieldValue(data, f.field))}</dd></div>))}
          </dl>
          {(view.related ?? []).map((r) => {
            const found = linked(data, r);
            const target = viewFor(ctx.manifest, "EntityDetailView", r.entity);
            return (
              <div key={r.relationship + r.direction + r.entity} className="rt-related" data-testid={`rt-related-${r.relationship}-${r.direction}`}>
                <h3>{r.label} <span className="muted small">({found.length})</span></h3>
                {found.length === 0 ? <p className="muted small">None recorded, or none shown to you.</p> : (
                  <ul className="rt-chips">{found.map((x) => (
                    <li key={x.id}>{target ? <button type="button" className="link" onClick={() => ctx.open(target.id, x.id)}>{x.id}</button> : x.id}</li>))}</ul>)}
              </div>);
          })}
          <p className="muted small">Shown as recorded. Links are recorded links: none is computed or inferred by this screen.</p>
        </>)}
    </section>
  );
}

export function Relationships({ view, ctx }: Props) {
  const { data, error, loading } = useLoad<RecordRow>(ctx, ctx.record ? `/objects/${encodeURIComponent(ctx.record)}` : null, [ctx.record]);
  const [states, setStates] = useState<Record<string, string>>({});
  const g = useMemo(() => (data ? graph(data) : null), [data]);
  useEffect(() => {  // each neighbour's own state, as recorded (bounded: the nodes drawn)
    if (!g) return;
    let live = true;
    Promise.all(g.nodes.filter((n) => !n.center).map((n) => call<RecordRow>(ctx.who, "GET", `/objects/${encodeURIComponent(n.id)}`)
      .then((r) => [n.id, cell(r.attributes?.status)] as const).catch(() => [n.id, ""] as const)))
      .then((pairs) => { if (live) setStates(Object.fromEntries(pairs)); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [g]);
  const back = viewFor(ctx.manifest, "EntityDetailView", view.entity ?? "");
  if (ctx.mode === "configuration" || !ctx.record) {
    return <section data-testid="rt-links"><h2>{view.title}</h2>{ctx.mode === "configuration" ? <NoData /> : <p className="muted">Open a record, then its relationships.</p>}
      <ul>{(view.related ?? []).map((r) => <li key={r.relationship + r.direction + r.entity}>{r.label}</li>)}</ul></section>;
  }
  const at = (id: string) => g?.nodes.find((n) => n.id === id);
  return (
    <section aria-labelledby="rt-links-title" data-testid="rt-links">
      <div className="row spread"><h2 id="rt-links-title">{view.title} <span className="muted">{ctx.record}</span></h2>
        {back && <button type="button" className="small" onClick={() => ctx.open(back.id, ctx.record)}>Back to the record</button>}</div>
      <Busy on={loading} /><Failed text={error} />
      {g && (
        <>
          <svg viewBox="0 0 640 380" className="rt-graph" role="img" aria-label={`Recorded links of ${ctx.record}`} data-testid="rt-graph">
            {g.edges.map((e, i) => { const a = at(e.from), b = at(e.to); return a && b ? (
              <g key={i}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="rt-edge" />
                <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} className="rt-edge-label">{e.label}</text></g>) : null; })}
            {g.nodes.map((n) => (
              <g key={n.id} className={n.center ? "rt-node rt-center" : "rt-node"}>
                <circle cx={n.x} cy={n.y} r={n.center ? 26 : 20} />
                <text x={n.x} y={n.y + 4} textAnchor="middle">{n.id}</text>
                <text x={n.x} y={n.y + (n.center ? 42 : 36)} textAnchor="middle" className="rt-node-type">{n.type}{states[n.id] ? ` · ${states[n.id]}` : ""}</text>
              </g>))}
          </svg>
          <table className="rt-table" data-testid="rt-link-table">
            <thead><tr><th scope="col">From</th><th scope="col">Link</th><th scope="col">To</th><th scope="col">State of the linked record</th></tr></thead>
            <tbody>{g.edges.map((e, i) => { const other = e.from === data?.id ? e.to : e.from; const target = viewFor(ctx.manifest, "EntityDetailView", at(other)?.type ?? "");
              return (<tr key={i}><td>{e.from}</td><td>{e.label}</td><td>{e.to}</td>
                <td>{states[other] ? <Status value={states[other]} /> : "—"} {target && <button type="button" className="link small" onClick={() => ctx.open(target.id, other)}>open</button>}</td></tr>); })}</tbody>
          </table>
          {g.edges.length === 0 && <p className="muted" data-testid="rt-empty">No link is recorded for this record, or none is shown to you.</p>}
          {g.omitted > 0 && <p className="muted small">{g.omitted} more recorded link(s) are not drawn.</p>}
          <p className="muted small" data-testid="rt-links-caution">Every line is a link somebody recorded. A link, or closeness in this picture, is not a finding about anybody: read the state and the source of each linked record.</p>
        </>)}
    </section>
  );
}

export function RecordForm({ view, ctx }: Props) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [id, setId] = useState("");
  const [result, setResult] = useState<{ kind: "preview" | "stored" | "refused"; text: string } | null>(null);
  const problems = formProblems(view, values);
  const real = ctx.mode === "simulation" && ctx.may.write_records;
  const submit = async () => {
    const body = { type: view.entity, id: id.trim(), attributes: formRecord(view, values), expected_revision: 0 };
    if (!real) { setResult({ kind: "preview", text: JSON.stringify(body, null, 1) }); ctx.say(`previewed a new ${view.entity}: nothing was sent`); return; }
    try {
      await call(ctx.who, "POST", "/objects", body);
      setResult({ kind: "stored", text: `Stored by the Engine as ${body.id}.` }); ctx.say(`the Engine stored ${body.id}`);
    } catch (e) { setResult({ kind: "refused", text: `The Engine refused: ${(e as Error).message}` }); }
  };
  return (
    <section aria-labelledby="rt-form-title" data-testid="rt-form">
      <h2 id="rt-form-title">{view.title}</h2>
      <p className="warn" data-testid="rt-form-mode">{real
        ? "You hold the unrestricted data permission on this use case: this form is sent to the Engine, which validates and stores it."
        : "Preview only: nothing you enter here is saved. Creating or changing records from an application needs a permission that does not exist yet (owner decision D24)."}</p>
      <label htmlFor="rt-form-id">Identifier</label>
      <input id="rt-form-id" value={id} onChange={(e) => setId(e.target.value)} maxLength={80} />
      {(view.fields ?? []).map((f) => (
        <div key={f.field}>
          <label htmlFor={`rt-f-${f.field}`}>{f.label}</label>
          {f.input === "select" ? (
            <select id={`rt-f-${f.field}`} value={values[f.field] ?? ""} onChange={(e) => setValues({ ...values, [f.field]: e.target.value })}>
              <option value="">—</option>{(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}</select>
          ) : f.input === "checkbox" ? (
            <select id={`rt-f-${f.field}`} value={values[f.field] ?? ""} onChange={(e) => setValues({ ...values, [f.field]: e.target.value })}>
              <option value="">—</option><option value="true">yes</option><option value="false">no</option></select>
          ) : (
            <input id={`rt-f-${f.field}`} type={f.input === "number" ? "text" : f.input === "date" ? "date" : "text"} inputMode={f.input === "number" ? "decimal" : undefined}
                   value={values[f.field] ?? ""} maxLength={500} onChange={(e) => setValues({ ...values, [f.field]: e.target.value })} />)}
        </div>))}
      {problems.length > 0 && <ul className="error" data-testid="rt-form-problems">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <button type="button" className="primary" disabled={!id.trim() || problems.length > 0} onClick={submit} data-testid="rt-form-submit">
        {real ? "Send to the Engine" : "Preview what would be sent"}</button>
      {result && (
        <div className="card" role="status" data-testid="rt-form-result">
          <strong>{result.kind === "preview" ? "Not saved. This is what would be sent:" : result.kind === "stored" ? "Saved." : "Not saved."}</strong>
          <pre className="rt-pre">{result.text}</pre>
        </div>)}
    </section>
  );
}

// -- work, decisions, audit ---------------------------------------------------------------------------------------
function RunCard({ run, ctx }: { run: Run; ctx: Ctx }) {
  return (
    <div className="card" data-testid="rt-run">
      <p><span className="rt-pill" data-testid="rt-run-status">{runLabel(run)}</span>{" "}
        <span className="muted small">run {run.run_id} · record {run.case_id}{run.started_by ? ` · asked by ${run.started_by}` : ""}</span></p>
      {run.hidden ? <p className="muted">This run involves records that are not shown to you.</p> : (
        <>
          <p data-testid="rt-run-outcome">{outcome(run)}</p>
          <ol className="rt-steps" data-testid="rt-run-steps">
            {(run.steps ?? []).map((s, i) => (
              <li key={i}><strong>{s.action}</strong>: {s.verdict}{s.outcome ? ` → ${s.outcome}` : ""}
                {s.reviewer ? ` · decided by ${s.reviewer}` : ""}{s.environment ? ` · ${s.environment} tool` : ""}
                {s.message ? <span className="muted small"> — {s.message}</span> : null}</li>))}
          </ol>
          {(run.steps ?? []).length === 0 && <p className="muted small">No action was performed.</p>}
          <p className="muted small" data-testid="rt-run-simulated">{run.simulated ? "Every tool was simulated: no other system was contacted or changed." : (run.steps ?? []).length ? "" : "Nothing was sent anywhere."}</p>
          {run.pending_review && <p className="warn" data-testid="rt-run-waits">A person named by the rules must decide. You cannot decide a request you made.</p>}
        </>)}
    </div>
  );
}

export function Workflow({ view, ctx }: Props) {
  const [record, setRecord] = useState(ctx.record ?? "");
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const records = useLoad<Page>(ctx, `/objects?type=${encodeURIComponent(view.entity ?? "")}&limit=100`, [view.id]);
  const runs = useLoad<{ items: Run[] }>(ctx, ctx.mode === "simulation" ? "/runs?limit=30" : null, [view.id]);
  const current = records.data?.items.find((r) => r.id === record);
  const start = async () => {
    setBusy(true); setError(""); setRun(null);
    try {
      const out = await call<Run>(ctx.who, "POST", "/runs", { case_template: view.case_template, root: record });
      setRun(out); ctx.say(`asked the Engine to handle ${record}: ${out.status}`);
      records.reload(); runs.reload();
    } catch (e) { setError(`The Engine refused: ${(e as Error).message}`); }
    setBusy(false);
  };
  const show = async (id: string) => {
    setError("");
    try { setRun(await call<Run>(ctx.who, "GET", `/runs/${encodeURIComponent(id)}`)); } catch (e) { setError((e as Error).message); }
  };
  const mine = (runs.data?.items ?? []).filter((r) => !record || r.case_id === record);
  const can = ctx.mode === "simulation" && ctx.may.start_runs;
  return (
    <section aria-labelledby="rt-work-title" data-testid="rt-work">
      <h2 id="rt-work-title">{view.title}</h2>
      <ol className="rt-states" aria-label="States" data-testid="rt-states">
        {(view.states ?? []).map((s) => <li key={s} className={current && cell(current.attributes.status) === s ? "rt-now" : ""}>{s}</li>)}
      </ol>
      <table className="rt-table" data-testid="rt-actions">
        <thead><tr><th scope="col">Action</th><th scope="col">What the rules say (the Engine decides, on each request)</th></tr></thead>
        <tbody>{(view.actions ?? []).map((a) => (
          <tr key={a.action}><th scope="row">{a.label}</th>
            <td>{a.rules.length === 0 ? <span className="muted">No rule names this action: done within the policy.</span> : (
              <ul className="rt-plain">{a.rules.map((id) => (
                <li key={id}><span className="rt-pill">{{ human_review: "a person decides", prohibition: "prohibited when", mandatory_step: "must come first", action_access: "who may" }[ctx.rules[id]?.kind ?? ""] ?? "rule"}</span>{" "}
                  {ctx.rules[id]?.description ?? id} <span className="muted small">({id})</span></li>))}</ul>)}</td></tr>))}</tbody>
      </table>
      {ctx.mode === "configuration" ? <NoData /> : (
        <div className="card">
          <label htmlFor="rt-work-record">Record</label>
          <select id="rt-work-record" value={record} onChange={(e) => { setRecord(e.target.value); setRun(null); }}>
            <option value="">Choose a record…</option>
            {(records.data?.items ?? []).map((r) => <option key={r.id} value={r.id}>{r.id} · {cell(r.attributes.status)}</option>)}
          </select>
          <Failed text={records.error} />
          <button type="button" className="primary" disabled={!can || !record || busy} onClick={start} data-testid="rt-start">
            Ask the solution to handle this record</button>
          {!can && <p className="muted small" data-testid="rt-start-why">{ctx.mode !== "simulation"
            ? "A preview starts nothing: runs exist in the engine-backed simulation only."
            : "You cannot start work here: the Engine does not give you that permission, or the use case's stage does not allow runs."}</p>}
          <p className="muted small">The Engine plans the work, checks every rule and either acts, waits for a person or refuses. This screen decides nothing.</p>
        </div>)}
      <Failed text={error} />
      {run && <RunCard run={run} ctx={ctx} />}
      {ctx.mode === "simulation" && (
        <div data-testid="rt-run-list">
          <h3>Earlier requests{record ? ` for ${record}` : ""}</h3>
          <Failed text={runs.error} />
          {mine.length === 0 ? <p className="muted small">None shown to you.</p> : (
            <ul className="rt-plain">{mine.map((r) => (
              <li key={r.run_id}><button type="button" className="link" onClick={() => show(r.run_id)}>{r.run_id}</button>{" "}
                {r.case_id} · <span className="rt-pill">{RUN_TEXT[r.status] ?? r.status}</span></li>))}</ul>)}
        </div>)}
    </section>
  );
}

export function ApprovalInbox({ view, ctx }: Props) {
  const usable = ctx.mode === "simulation" && view.available !== false;
  const { data, error, loading, reload } = useLoad<{ items: Review[] }>(ctx, usable ? "/reviews" : null, [view.id]);
  const [comment, setComment] = useState("");
  const [message, setMessage] = useState("");
  const decide = async (review: Review, approved: boolean) => {
    setMessage("");
    try {
      const out = await call<Run>(ctx.who, "POST", `/reviews/${encodeURIComponent(review.review_id)}/decision`, { approved, comment });
      setMessage(`Recorded by the Engine: ${approved ? "approved" : "refused"}. The run is now: ${RUN_TEXT[out.status] ?? out.status}.`);
      ctx.say(`decided ${review.review_id}: ${approved ? "approved" : "refused"}`); setComment(""); reload();
    } catch (e) { setMessage(`The Engine refused: ${(e as Error).message}`); }
  };
  return (
    <section aria-labelledby="rt-inbox-title" data-testid="rt-inbox">
      <h2 id="rt-inbox-title">{view.title}</h2>
      <ul className="rt-plain">{(view.rules ?? []).map((id) => <li key={id}><span className="rt-pill">a person decides</span> {ctx.rules[id]?.description ?? id} <span className="muted small">({id})</span></li>)}</ul>
      {!usable && <p className="muted" data-testid="rt-inbox-unavailable">{ctx.mode !== "simulation" ? "A preview shows no request: decisions exist in the engine-backed simulation only."
        : view.unavailable_because ?? "The Engine does not let you decide reviews."}</p>}
      <Busy on={loading} /><Failed text={error} />
      {message && <p role="status" data-testid="rt-inbox-message">{message}</p>}
      {usable && data && data.items.length === 0 && <p className="muted" data-testid="rt-empty">Nothing waits for you.</p>}
      {(data?.items ?? []).map((r) => (
        <div className="card" key={r.review_id} data-testid="rt-review">
          <p><strong>{r.request.action ?? r.action}</strong> on record {r.request.case_id} <span className="muted small">(run {r.run_id})</span></p>
          <ul className="rt-plain">{(r.request.reasons ?? []).map((x) => <li key={x}>{x}</li>)}</ul>
          <p className="muted small">Rules: {(r.request.rule_ids ?? []).join(", ") || "—"} · decided by: {r.reviewers.join(", ")}</p>
          <label htmlFor={`rt-c-${r.review_id}`}>Comment (kept with your decision)</label>
          <input id={`rt-c-${r.review_id}`} value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} />
          <div className="row">
            <button type="button" className="primary" disabled={!ctx.may.decide_reviews} onClick={() => decide(r, true)} data-testid="rt-approve">Approve</button>
            <button type="button" disabled={!ctx.may.decide_reviews} onClick={() => decide(r, false)} data-testid="rt-refuse">Refuse</button>
          </div>
        </div>))}
    </section>
  );
}

export function AuditTimeline({ view, ctx, activity }: Props & { activity: string[] }) {
  const usable = ctx.mode === "simulation" && view.available !== false;
  const runs = useLoad<{ items: Run[] }>(ctx, usable ? "/runs?limit=30" : null, [view.id]);
  const [chosen, setChosen] = useState("");
  const audit = useLoad<{ verified: boolean; entries: AuditEntry[] }>(ctx, usable && chosen ? `/runs/${encodeURIComponent(chosen)}/audit` : null, [chosen]);
  return (
    <section aria-labelledby="rt-audit-title" data-testid="rt-audit">
      <h2 id="rt-audit-title">{view.title}</h2>
      {!usable && <p className="muted" data-testid="rt-audit-unavailable">{ctx.mode !== "simulation" ? "A preview has no audit trail: the trail is the Engine's record of real requests."
        : view.unavailable_because ?? "The Engine does not show you audit trails."}</p>}
      {usable && (
        <>
          <label htmlFor="rt-audit-run">Request</label>
          <select id="rt-audit-run" value={chosen} onChange={(e) => setChosen(e.target.value)}>
            <option value="">Choose a request…</option>
            {(runs.data?.items ?? []).map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id} · {r.case_id} · {RUN_TEXT[r.status] ?? r.status}</option>)}
          </select>
          <Failed text={runs.error || audit.error} /><Busy on={audit.loading} />
          {audit.data && (
            <div className="card" data-testid="rt-audit-engine">
              <h3>Engine record <span className={audit.data.verified ? "rt-pill rt-ok" : "rt-pill rt-bad"} data-testid="rt-audit-verified">
                {audit.data.verified ? "signed chain verifies" : "the chain does NOT verify"}</span></h3>
              <ol className="rt-steps">{timeline(audit.data.entries).map((t) => <li key={t.seq}><strong>{t.label}</strong>: {t.detail} <span className="muted small">#{t.seq}</span></li>)}</ol>
              <p className="muted small">{audit.data.entries.length} signed entries, kept by the Engine. This screen only reads them.</p>
            </div>)}
        </>)}
      <div className="card" data-testid="rt-audit-interface">
        <h3>This screen, this session <span className="rt-pill">not an audit record</span></h3>
        {activity.length === 0 ? <p className="muted small">Nothing yet.</p> : <ul className="rt-plain">{activity.map((a, i) => <li key={i}>{a}</li>)}</ul>}
        <p className="muted small">Kept in this browser tab only, and lost when it closes. Evidence is the Engine&apos;s record above.</p>
      </div>
    </section>
  );
}

export function Dashboard({ view, ctx }: Props) {
  return (
    <section aria-labelledby="rt-dash-title" data-testid="rt-dashboard">
      <h2 id="rt-dash-title">{view.title}</h2>
      {ctx.mode === "configuration" && <NoData />}
      <div className="rt-tiles">{(view.tiles ?? []).map((t) => <Tile key={t.entity} entity={t.entity} label={t.label} ctx={ctx} />)}</div>
    </section>
  );
}
function Tile({ entity, label, ctx }: { entity: string; label: string; ctx: Ctx }) {
  const { data, error } = useLoad<Page>(ctx, `/objects?type=${encodeURIComponent(entity)}&limit=100`, [entity]);
  const list = viewFor(ctx.manifest, "EntityListView", entity);
  const loaded = data?.items ?? [];
  return (
    <div className="card rt-tile" data-testid={`rt-tile-${entity}`}>
      <h3>{label}</h3>
      {ctx.mode !== "configuration" && <p className="rt-big">{data ? data.total ?? loaded.length : "…"}</p>}
      <Failed text={error} />
      <ul className="rt-plain">{countBy(loaded).map(([state, n]) => <li key={state}><Status value={state} /> {n}</li>)}</ul>
      {data && (data.total ?? 0) > loaded.length && <p className="muted small">By state: the first {loaded.length} only.</p>}
      {list && <button type="button" className="link" onClick={() => ctx.open(list.id)}>Open the list</button>}
      <p className="muted small">Counts are of the records shown to you.</p>
    </div>
  );
}
