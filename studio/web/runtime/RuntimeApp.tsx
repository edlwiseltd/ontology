"use client";

// The application runtime: it renders a business application from a manifest the Engine validated and tailored for
// this caller. It is not Studio and shares no session with it. It holds no rule, no permission and no audit trail
// of its own: what it shows is what the Engine answered, and a button it hides is hidden for comfort, not security.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { call, enginePath, EngineError, getToken, setToken, type Caller } from "./client";
import About from "./about";
import { groupNavigation, incompatibility, NAV_FILTER_FROM, short, supported, unsupportedViews } from "./model";
import DesignStatus from "./status";
import type { Application, Manifest, May, Mode, RuleInfo, View } from "./types";
import { MODE_LABEL } from "./types";
import { ApprovalInbox, AuditTimeline, Dashboard, EntityDetail, EntityList, RecordForm, Relationships, Workflow, type Ctx } from "./views";

export interface Preview { manifest: Manifest; mode: "configuration" | "synthetic"; token: () => string | null }
const NOTHING: May = { read_records: false, start_runs: false, decide_reviews: false, read_audit: false, write_records: false };

function Render({ view, ctx, activity }: { view: View; ctx: Ctx; activity: string[] }) {
  switch (view.type) {  // the registry: a closed list. A type that is not here is never rendered
    case "DashboardView": return <Dashboard view={view} ctx={ctx} />;
    case "EntityListView": return <EntityList view={view} ctx={ctx} />;
    case "EntityDetailView": return <EntityDetail view={view} ctx={ctx} />;
    case "RelationshipView": return <Relationships view={view} ctx={ctx} />;
    case "RecordFormView": return <RecordForm view={view} ctx={ctx} />;
    case "WorkflowView": return <Workflow view={view} ctx={ctx} />;
    case "ApprovalInboxView": return <ApprovalInbox view={view} ctx={ctx} />;
    case "AuditTimelineView": return <AuditTimeline view={view} ctx={ctx} activity={activity} />;
    default: return <p className="warn" data-testid="rt-unsupported">This screen ({view.type}) is not supported by this renderer and is not shown.</p>;
  }
}

export default function RuntimeApp({ workspace, useCase, preview }: { workspace: string; useCase: string; preview?: Preview }) {
  const base = enginePath(workspace, useCase);
  const [app, setApp] = useState<Application | null>(null);
  const [rules, setRules] = useState<Record<string, RuleInfo>>({});
  const [state, setState] = useState<"signed-out" | "loading" | "ready" | "refused">(preview ? "ready" : "loading");
  const [refusal, setRefusal] = useState<{ status: number; message: string; details: Record<string, unknown> } | null>(null);
  const [at, setAt] = useState<{ view: string; record?: string } | null>(null);
  const [activity, setActivity] = useState<string[]>([]);
  const [token, setTokenInput] = useState("");
  const [about, setAbout] = useState(false);
  const [find, setFind] = useState("");
  const lastAnswer = useRef<Date | null>(null);  // when this screen last heard from the Engine: a fact about the screen
  const heard = useCallback(() => { lastAnswer.current = new Date(); }, []);

  const who: Caller = useMemo(() => ({ base, token: preview ? preview.token : getToken, configuration: app?.running.configuration, heard }),
                              [base, preview, app, heard]);
  const load = useCallback(async () => {
    if (preview) return;
    if (!getToken()) { setState("signed-out"); return; }
    setState("loading"); setRefusal(null);
    const me: Caller = { base, token: getToken, heard };
    try {
      const found = await call<Application>(me, "GET", "/application");
      setApp(found);
      const model = await call<{ rules: RuleInfo[] }>({ ...me, configuration: found.running.configuration }, "GET", "/ontology");
      setRules(Object.fromEntries(model.rules.map((r) => [r.id, r])));
      setState("ready");
    } catch (e) {
      const err = e as EngineError;
      if (err.status === 401) { setToken(null); setState("signed-out"); setRefusal({ status: 401, message: "Your token was refused.", details: {} }); }
      else { setApp(null); setRefusal({ status: err.status ?? 0, message: err.message, details: err.details ?? {} }); setState("refused"); }
    }
  }, [base, preview, heard]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {  // a designer's preview explains rules with what the model says, when it may be read
    if (!preview || preview.mode === "configuration") return;
    call<{ rules: RuleInfo[] }>({ base, token: preview.token }, "GET", "/ontology")
      .then((m) => setRules(Object.fromEntries(m.rules.map((r) => [r.id, r])))).catch(() => undefined);
  }, [preview, base]);

  const manifest = preview ? preview.manifest : app?.manifest ?? null;
  const mode: Mode = preview ? preview.mode : "simulation";
  const may: May = preview ? { ...NOTHING, read_records: preview.mode === "synthetic" } : app?.you.may ?? NOTHING;
  const views = useMemo(() => (manifest?.views ?? []).filter(supported), [manifest]);
  const navigation = (manifest?.navigation ?? []).filter((n) => views.some((v) => v.id === n.view));
  const current = views.find((v) => v.id === at?.view) ?? views.find((v) => v.id === navigation[0]?.view) ?? views[0];
  const open = useCallback((view: string, record?: string) => { setAbout(false); setAt({ view, record }); }, []);
  const groups = groupNavigation(navigation, views, find);
  const say = useCallback((line: string) => setActivity((a) => [...a.slice(-49), `${new Date().toLocaleTimeString()} · ${line}`]), []);

  if (state === "signed-out") {
    return (
      <main className="signin" data-testid="rt-signin">
        <h1>Application</h1>
        <p className="muted">{workspace} / {useCase}. Sign in with your own access token. This application has no account of its own: the Engine decides what you see and may do.</p>
        {refusal && <p className="error" role="alert">{refusal.message}</p>}
        <form onSubmit={(e) => { e.preventDefault(); setToken(token.trim()); setTokenInput(""); void load(); }}>
          <label htmlFor="rt-token">Access token</label>
          <input id="rt-token" type="password" autoComplete="off" value={token} onChange={(e) => setTokenInput(e.target.value)} />
          <button type="submit" className="primary" disabled={!token.trim()}>Open the application</button>
        </form>
      </main>);
  }
  if (state === "loading") return <main className="signin"><p role="status">Asking the Engine for the application…</p></main>;
  const incompatible = manifest ? incompatibility(manifest) : null;
  if (state === "refused" || !manifest || !current || incompatible) {
    const mismatch = refusal?.status === 409;
    return (
      <main className="signin" data-testid="rt-refused">
        <h1>{mismatch ? "This application is not shown" : refusal?.status === 404 ? "No application here" : "The Engine refused"}</h1>
        <p className={mismatch ? "warn" : "error"} role="alert" data-testid="rt-refusal">{incompatible ?? refusal?.message ?? "The design has no screen this renderer supports."}</p>
        {mismatch && typeof refusal?.details.running === "string" && (
          <p className="muted small" data-testid="rt-refusal-detail">Designed for configuration {short(String(refusal.details.designed_for ?? refusal.details.expected ?? ""))};
            running now: {short(String(refusal.details.running))}. Nothing is shown until a designer has checked the application against what runs.</p>)}
        <div className="row"><button type="button" onClick={() => void load()}>Ask again</button>
          <button type="button" onClick={() => { setToken(null); setState("signed-out"); setRefusal(null); }}>Sign out</button></div>
      </main>);
  }

  const ctx: Ctx = { who, manifest, mode, may, rules, open, say, record: at?.record };
  const dropped = unsupportedViews(manifest);
  return (
    <div className={`rt rt-${manifest.presentation.density}`} data-accent={manifest.presentation.accent} data-testid="rt-app" data-mode={mode}>
      <header className="rt-bar">
        <div>
          <strong className="rt-title" data-testid="rt-title">{manifest.title}</strong>
          <span className="rt-pill rt-mode" data-testid="rt-mode">{MODE_LABEL[mode]}</span>
          <span className="rt-pill" data-testid="rt-production">Production: unavailable</span>
        </div>
        <div className="small muted" data-testid="rt-release">
          Model {manifest.binding.model} · configuration {short(manifest.binding.configuration)}
          {app ? ` · stage ${app.stage ?? "none"} · design revision ${app.revision} (${app.status})` : " · a design that is not saved yet"}
        </div>
        {app && <details className="small"><summary data-testid="rt-status-summary">Status of this design: {app.governance.summary}</summary>
          <DesignStatus governance={app.governance} testid="rt-status" /></details>}
        {app && (
          <div className="small row">
            <span data-testid="rt-you">{app.you.name}: {[may.read_records && "reads records", may.start_runs && "starts work", may.decide_reviews && "decides reviews",
              may.read_audit && "reads audit", may.write_records && "writes records"].filter(Boolean).join(", ") || "no permission"}</span>
            <button type="button" className="small" onClick={() => void load()} data-testid="rt-reload">Reload</button>
            <button type="button" className="small" onClick={() => { setToken(null); setApp(null); setState("signed-out"); }}>Sign out</button>
          </div>)}
      </header>
      <div className="rt-body">
        <nav aria-label="Application" className="rt-nav" data-testid="rt-nav">
          {navigation.length > NAV_FILTER_FROM && (
            <div className="rt-nav-find">
              <label htmlFor="rt-nav-find" className="small">Find a screen</label>
              <input id="rt-nav-find" value={find} onChange={(e) => setFind(e.target.value)} maxLength={60} data-testid="rt-nav-find" />
            </div>)}
          {groups.map((g) => (
            <div key={g.label} className="rt-nav-group" data-testid={`rt-nav-group-${g.label}`}>
              <h3 id={`rt-nav-${g.label}`}>{g.label}</h3>
              <ul aria-labelledby={`rt-nav-${g.label}`}>{g.items.map((n) => (
                <li key={n.view} data-nav={n.view}><button type="button" aria-current={!about && current.id === n.view ? "page" : undefined} onClick={() => open(n.view)}>{n.label}</button></li>))}</ul>
            </div>))}
          {groups.length === 0 && <p className="muted small" role="status" data-testid="rt-nav-none">No screen has that text in its name.</p>}
          {app && <button type="button" className="rt-about-open" aria-current={about ? "page" : undefined} onClick={() => setAbout(true)} data-testid="rt-about-open">About this application</button>}
          <details className="rt-cannot" data-testid="rt-cannot">
            <summary>What this application cannot do ({manifest.unavailable.length})</summary>
            <ul>{manifest.unavailable.map((u) => <li key={u.feature} className="small">{u.reason}</li>)}</ul>
          </details>
        </nav>
        <main className="rt-main">
          {dropped.length > 0 && <p className="warn" data-testid="rt-dropped">{dropped.length} screen(s) of this design are of a kind this renderer does not support and are not shown: {dropped.map((v) => v.type).join(", ")}.</p>}
          {about && app ? <About app={app} lastAnswer={lastAnswer.current} />
            : current.available === false && mode === "simulation" && current.type !== "ApprovalInboxView" && current.type !== "AuditTimelineView"
            ? <p className="muted">{current.unavailable_because}</p> : <Render key={`${current.id}:${at?.record ?? ""}`} view={current} ctx={ctx} activity={activity} />}
        </main>
      </div>
    </div>
  );
}
