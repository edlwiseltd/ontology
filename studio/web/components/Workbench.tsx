"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, getToken, setToken } from "@/lib/api";
import type { Me, OntologySummary, Template, UseCase } from "@/lib/types";
import AccessView from "./AccessView";
import DesignView from "./DesignView";
import OnboardingView from "./OnboardingView";
import OntologyView from "./OntologyView";
import ReleasesView from "./ReleasesView";
import StageOverview, { LABELS } from "./StageOverview";

type View = "overview" | "onboarding" | "model" | "design" | "releases";
type Status = "signed-out" | "loading" | "ready" | "unavailable";

export default function Workbench() {
  const [status, setStatus] = useState<Status>("loading");
  const [signInError, setSignInError] = useState("");
  const [me, setMe] = useState<Me | null>(null);
  const [useCases, setUseCases] = useState<UseCase[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<UseCase | null>(null);
  const [view, setView] = useState<View>("overview");
  const [ontology, setOntology] = useState<OntologySummary | null>(null);
  const [ontologyError, setOntologyError] = useState("");
  const [entity, setEntity] = useState<string | null>(null);
  const [creating, setCreating] = useState<Template[] | null>(null);
  const [createError, setCreateError] = useState("");
  const [theme, setTheme] = useState<"auto" | "light" | "dark">("auto");
  const [area, setArea] = useState<"use-cases" | "access">("use-cases");

  // The use case the person chose last. Answers that arrive for an earlier choice (a refresh started before they
  // clicked another use case) are dropped, so a late answer never puts another use case's detail on screen.
  const current = useRef<string | null>(null);

  const signOut = useCallback(() => {
    setToken(null); setMe(null); setUseCases([]); setSelected(null); setDetail(null); setOntology(null);
    current.current = null; setArea("use-cases");
    setStatus("signed-out");
  }, []);

  // The workspace is always explicit: the platform answers for the one named here (or the identity's first one),
  // and every later call names it in its path.
  const load = useCallback(async (workspace?: string) => {
    try {
      const who = await api.me(workspace);
      setMe(who);
      setUseCases((await api.useCases(who.workspace.id)).items);
      setStatus("ready");
    } catch (e) {
      const code = (e as { status?: number }).status;
      if (code === 401) { setSignInError("Your token was refused."); signOut(); }
      else { setStatus("unavailable"); setSignInError((e as Error).message); }
    }
  }, [signOut]);

  useEffect(() => { if (getToken()) void load(); else setStatus("signed-out"); }, [load]);
  useEffect(() => {
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const switchWorkspace = useCallback(async (id: string) => {
    current.current = null;
    setSelected(null); setDetail(null); setOntology(null); setEntity(null); setCreating(null);
    await load(id);
  }, [load]);

  const open = useCallback(async (id: string) => {
    if (!me) return;
    current.current = id;
    setArea("use-cases");
    setSelected(id); setOntology(null); setOntologyError(""); setEntity(null);
    const uc = await api.useCase(me.workspace.id, id);
    if (current.current !== id) return;
    setDetail(uc);
    try {
      const model = await api.ontology(uc.path);
      if (current.current === id) setOntology(model);
    } catch (e) { if (current.current === id) setOntologyError((e as Error).message); }
  }, [me]);

  const refresh = useCallback(async () => {
    if (!me) return;
    const id = current.current;
    setUseCases((await api.useCases(me.workspace.id)).items);
    if (!id) return;
    const uc = await api.useCase(me.workspace.id, id);
    if (current.current === id) setDetail(uc);
  }, [me]);

  async function signIn(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const input = ev.currentTarget.elements.namedItem("token") as HTMLInputElement;
    setToken(input.value.trim()); input.value = ""; setSignInError(""); setStatus("loading");
    await load();
  }

  async function startCreate() {
    setCreateError("");
    try { setCreating((await api.templates()).items); } catch (e) { setCreateError((e as Error).message); setCreating([]); }
  }

  async function create(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    if (!me) return;
    const f = new FormData(ev.currentTarget);
    try {
      const uc = await api.createUseCase(me.workspace.id, String(f.get("id")), String(f.get("name")), String(f.get("template")));
      setCreating(null);
      await refresh();
      await open(uc.id);
    } catch (e) { setCreateError((e as Error).message); }
  }

  if (status === "signed-out" || status === "unavailable") {
    return (
      <main className="signin">
        <h1>Autology Studio</h1>
        <p className="muted">Sign in with the API token your administrator gave you. It stays in this browser tab.</p>
        {status === "unavailable" && <p className="warn" role="alert">The platform is unavailable: {signInError}</p>}
        <form onSubmit={signIn}>
          <label htmlFor="token">API token</label>
          <input id="token" name="token" type="password" autoComplete="off" required />
          <button type="submit" className="primary">Open my workspace</button>
        </form>
        {status === "signed-out" && signInError && <p className="error" role="alert">{signInError}</p>}
      </main>
    );
  }
  if (status === "loading" || !me) return <main className="signin" aria-busy="true"><p className="muted">Loading…</p></main>;

  return (
    <div className="workbench">
      <header className="bar">
        <div className="brand"><span aria-hidden="true">◆</span> Autology Studio</div>
        <div className="context" aria-label="Context">
          {me.tenant && <><span className="muted" data-testid="tenant-name">{me.tenant.name}</span><span aria-hidden="true">›</span></>}
          {(me.workspaces?.length ?? 0) > 1 ? (
            <>
              <label className="sr-only" htmlFor="workspace">Workspace</label>
              <select id="workspace" value={me.workspace.id} onChange={(e) => void switchWorkspace(e.target.value)}>
                {me.workspaces!.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </>
          ) : <span data-testid="workspace-name">{me.workspace.name}</span>}
          {area === "access" ? <><span aria-hidden="true">›</span><span>Access</span></>
            : detail && <><span aria-hidden="true">›</span><span>{detail.name}</span>
            <span className={`stage stage-${detail.effective_stage}`}>{LABELS[detail.stage]}</span></>}
        </div>
        <div className="who">
          <span>{me.member}</span>{me.workspace_admin && <span className="badge">admin</span>}
          <label className="sr-only" htmlFor="theme">Theme</label>
          <select id="theme" value={theme} onChange={(e) => setTheme(e.target.value as typeof theme)}>
            <option value="auto">Auto theme</option><option value="light">Light</option><option value="dark">Dark</option>
          </select>
          <button type="button" className="link" onClick={signOut}>Sign out</button>
        </div>
      </header>

      <nav className="nav" aria-label="Use cases">
        <div className="row spread">
          <h2>Use cases</h2>
          {me.workspace_admin && <button type="button" className="small" onClick={startCreate}>New</button>}
        </div>
        {useCases.length === 0 && <p className="muted small">No use case is open to you in this workspace.</p>}
        <ul className="uc-list">
          {useCases.map((uc) => (
            <li key={uc.id}>
              <button type="button" aria-current={area === "use-cases" && uc.id === selected ? "true" : undefined}
                      onClick={() => open(uc.id)}>
                <span>{uc.name}<br /><span className="muted small">{uc.id}</span></span>
                <span className={`stage stage-${uc.effective_stage}`}>{LABELS[uc.stage]}{uc.stale ? " · stale" : ""}</span>
              </button>
            </li>
          ))}
        </ul>
        {creating && (
          <form className="card" onSubmit={create} aria-labelledby="new-title">
            <h3 id="new-title">New use case</h3>
            <label htmlFor="c-template">Approved template</label>
            <select id="c-template" name="template" required>
              {creating.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <label htmlFor="c-id">Identifier</label>
            <input id="c-id" name="id" required pattern="[a-z0-9][a-z0-9\-]{0,62}" />
            <label htmlFor="c-name">Name</label>
            <input id="c-name" name="name" required maxLength={120} />
            <div className="row">
              <button type="submit" className="primary">Create in Draft</button>
              <button type="button" onClick={() => setCreating(null)}>Cancel</button>
            </div>
            {createError && <p className="error" role="alert">{createError}</p>}
          </form>
        )}
        <h2 className="section">Workspace</h2>
        <ul className="uc-list">
          <li>
            <button type="button" aria-current={area === "access" ? "true" : undefined} data-testid="open-access"
                    onClick={() => setArea("access")}>
              <span>Access<br /><span className="muted small">members, grants, approvals</span></span>
            </button>
          </li>
        </ul>
        <h2 className="section">Coming next</h2>
        <ul className="planned small muted" aria-label="Planned areas">
          <li>AI Architect with a language model — blocked on D7/D10 (a sandbox architect and blueprints work today)</li>
          <li>Processes, organisation, agents — planned</li>
        </ul>
      </nav>

      <main className="main">
        {area === "access" ? (
          <AccessView key={me.workspace.id} me={me}
                      onOwnToken={(token) => { setToken(token); void load(me.workspace.id); }} />
        ) : !detail ? <p className="muted empty">Choose a use case.</p> : (
          <>
            <div role="tablist" aria-label="Views" className="tabs">
              <button role="tab" aria-selected={view === "overview"} onClick={() => setView("overview")}>Overview</button>
              <button role="tab" aria-selected={view === "onboarding"} onClick={() => setView("onboarding")}>Onboarding</button>
              <button role="tab" aria-selected={view === "model"} onClick={() => setView("model")}>Active model</button>
              <button role="tab" aria-selected={view === "design"} onClick={() => setView("design")}>Design (draft)</button>
              <button role="tab" aria-selected={view === "releases"} onClick={() => setView("releases")}>Releases</button>
            </div>
            {view === "overview" && <StageOverview workspace={me.workspace.id} useCase={detail} admin={me.workspace_admin}
                                                   onChanged={refresh} />}
            {view === "model" && (ontologyError ? <p className="error" role="alert">{ontologyError}</p>
              : ontology ? <OntologyView ontology={ontology} selected={entity} onSelect={setEntity} />
              : <p className="muted" aria-busy="true">Loading the model…</p>)}
            {view === "onboarding" && <OnboardingView key={detail.id} workspace={me.workspace.id} useCase={detail}
                                                      admin={me.workspace_admin} />}
            {view === "design" && <DesignView key={detail.id} path={detail.path} admin={me.workspace_admin} />}
            {view === "releases" && <ReleasesView key={detail.id} workspace={me.workspace.id} useCase={detail}
                                                  member={me.member} admin={me.workspace_admin} onChanged={refresh} />}
          </>
        )}
      </main>
    </div>
  );
}
