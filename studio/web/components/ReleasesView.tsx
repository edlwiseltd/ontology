"use client";

// Releases of a use case (REL-1a, STU-6). Every rule is the platform's: who may propose, approve and activate,
// "never the proposer", "only what runs can be activated". Buttons hidden here are conveniences only; the browser
// tests prove the platform refuses the same calls made directly.

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Release, ReleaseState, UseCase } from "@/lib/types";

const STATUS: Record<string, string> = { proposed: "proposed", approved: "approved", active: "active",
                                         superseded: "superseded" };

export default function ReleasesView({ workspace, useCase, member, admin, onChanged }: {
  workspace: string; useCase: UseCase; member: string; admin: boolean; onChanged: () => void;
}) {
  const [state, setState] = useState<ReleaseState | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [draftRevision, setDraftRevision] = useState<number>(0);
  const [draftAuthor, setDraftAuthor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [inspected, setInspected] = useState<Release | null>(null);
  const me = `${member}@${workspace}`;

  const inspect = async (n: number) => {
    setError("");
    try { setInspected(await api.release(workspace, useCase.id, n)); } catch (e) { setError((e as Error).message); }
  };

  const load = useCallback(async () => {
    setError("");
    try {
      const rel = await api.releases(workspace, useCase.id);
      setState(rel);
      // the platform tells whoever may publish which draft revision is saved and who saved it
      setDraftRevision(rel.draft?.revision ?? 0);
      setDraftAuthor(rel.draft?.author ?? null);
    } catch (e) { setError((e as Error).message); }
  }, [workspace, useCase.id]);

  useEffect(() => { setState(null); setMessage(""); setInspected(null); load(); }, [load]);

  async function act(what: string, call: () => Promise<unknown>) {
    setBusy(true); setError(""); setMessage("");
    try {
      await call();
      setMessage(what);
      setNote(""); setReason("");
      await load();
      onChanged();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  if (!state) return error ? <p className="error" role="alert">{error}</p>
    : <p className="muted" aria-busy="true">Loading releases…</p>;

  const running = state.running_fingerprint;
  const needReason = !reason.trim();
  const actions = (r: Release) => {
    const out = [<button key="i" className="small" data-testid={`inspect-${r.number}`} onClick={() => inspect(r.number)}>Contents</button>];
    if (state.may_approve && r.status === "proposed" && r.proposed_by !== me)
      out.push(<button key="a" className="small" disabled={busy || needReason}
                       onClick={() => act(`Release ${r.number} approved`, () => api.releaseAction(workspace, useCase.id, r.number, "approve", reason))}>Approve</button>);
    if (r.status === "approved" && (admin || r.approved_by === me))
      out.push(<button key="v" className="small" disabled={busy || needReason}
                       onClick={() => act(`Approval of release ${r.number} revoked`, () => api.releaseAction(workspace, useCase.id, r.number, "revoke", reason))}>Revoke approval</button>);
    if (admin && r.approved_by && r.status !== "active") {
      // One step, decided by the platform: it puts the release's model in place, switches the engine once the
      // requests in flight have finished, and puts everything back if that fails. An older release is a rollback.
      const back = !!state.active && state.active.number > r.number;
      out.push(<button key="t" className="small" disabled={busy || needReason} data-testid={back ? "rollback" : "activate"}
                       onClick={() => act(back ? `Rolled back to release ${r.number}` : `Release ${r.number} activated`,
                                          () => api.activateRelease(workspace, useCase.id, r.number, reason))}>
        {back ? "Roll back to this release" : "Activate"}</button>);
    }
    return out;
  };

  return (
    <section aria-labelledby="rel-title" className="overview">
      <div className="row spread">
        <h2 id="rel-title">Releases</h2>
        <button type="button" className="small" disabled={busy} onClick={() => void load()} data-testid="refresh-releases">Refresh</button>
      </div>
      <p className="muted small">
        Running configuration <code data-testid="running">{running.slice(0, 12)}</code> ·{" "}
        {state.active ? <>active release <strong data-testid="active-release">{state.active.number}</strong></> : "no active release"}
        <span className="source"> · decided by the platform</span>
      </p>
      {state.integrity_problem && <p className="warn" role="alert">{state.integrity_problem}</p>}
      {state.drift && <p className="warn" role="alert" data-testid="drift">
        The running configuration is not the active release: nothing runs until a person activates an approved release of it.</p>}
      {message && <p className="ok" role="status">{message}</p>}
      {error && <p className="error" role="alert">{error}</p>}

      {(state.may_propose || state.may_approve) && (
        <div className="card">
          <label htmlFor="rel-reason">Reason for an approval, revocation, activation or rollback</label>
          <input id="rel-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500}
                 placeholder="what you checked, or why" />
        </div>
      )}

      {state.may_propose && (
        <form className="card" aria-labelledby="propose-title" onSubmit={(e) => {
          e.preventDefault();
          act("Release proposed: another person with release authority must approve it",
              () => api.proposeRelease(workspace, useCase.id, note));
        }}>
          <h3 id="propose-title">Propose the running configuration</h3>
          <p className="muted small">A release is an immutable snapshot of what runs now. You cannot approve your own.</p>
          <input id="rel-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500}
                 placeholder="what this release changes" aria-label="Release note" />
          <button type="submit" disabled={busy || !note.trim()}>Propose release</button>
        </form>
      )}

      {(admin || state.may_approve) && (
        <div className="card" data-testid="publish-card">
          <h3>Publish a Studio draft</h3>
          {draftRevision > 0 ? (
            <>
              <p className="muted small">Makes saved draft revision {draftRevision} this use case&apos;s model, with its agents
                and simulated tools. Nothing runs on it until a release of it is approved by another person and activated.</p>
              {draftAuthor === member && <p className="warn small" data-testid="publish-needs-another">
                You saved this revision: another person with release authority must publish it (the platform refuses the
                author).</p>}
              <button type="button" disabled={busy || needReason || draftAuthor === member} data-testid="publish-draft"
                      onClick={() => act(`Draft revision ${draftRevision} published: propose a release of it`,
                                         () => api.publishDraft(workspace, useCase.id, draftRevision, reason))}>
                Publish draft revision {draftRevision}</button>
            </>
          ) : <p className="muted small">No saved draft yet (Onboarding or Design tab).</p>}
        </div>
      )}

      <div className="card">
        <h3>All releases</h3>
        {state.items.length === 0 ? <p className="muted small">No release yet.</p> : (
          <table className="releases" aria-label="Releases">
            <thead><tr><th>#</th><th>Status</th><th>Fingerprint</th><th>Proposed by</th><th>Approved by</th><th /></tr></thead>
            <tbody>
              {[...state.items].reverse().map((r) => (
                <tr key={r.number} data-status={r.status}>
                  <td>{r.number}</td>
                  <td><span className="badge">{STATUS[r.status] ?? r.status}</span>
                    {r.fingerprint === running ? <span className="muted small"> · what runs</span> : null}</td>
                  <td><code>{r.fingerprint.slice(0, 12)}</code></td>
                  <td>{r.proposed_by}<div className="muted small">{r.note}</div></td>
                  <td>{r.approved_by ?? "—"}</td>
                  <td className="row">{actions(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {inspected?.components && (
        <div className="card" data-testid="release-contents">
          <h3>Release {inspected.number} contains</h3>
          <p className={inspected.verification?.coherent ? "ok small" : "error small"} role="status" data-testid="release-verification">
            {inspected.verification?.coherent
              ? "Coherent: the model, the agents and the tools refer to one another correctly, and the snapshot matches its fingerprint."
              : `Not coherent, so it cannot be activated: ${(inspected.verification?.problems ?? []).join("; ")}`}
            {inspected.verification && !inspected.verification.fingerprint_matches && " The snapshot does not match its fingerprint."}
            <span className="source"> · verified by the engine from the release&apos;s own snapshot</span></p>
          <table className="releases" aria-label={`Parts of release ${inspected.number}`}>
            <thead><tr><th scope="col">Part</th><th scope="col">Content</th><th scope="col">Fingerprint</th></tr></thead>
            <tbody>
              <tr><th scope="row">Business model</th><td>{inspected.components.model.ref ?? "—"} · {inspected.components.model.entities} entities</td>
                <td><code>{inspected.components.model.fingerprint}</code></td></tr>
              <tr><th scope="row">Rules</th><td>{inspected.components.rules.count}</td><td><code>{inspected.components.rules.fingerprint}</code></td></tr>
              <tr><th scope="row">Action definitions</th><td>{inspected.components.actions.count}</td><td><code>{inspected.components.actions.fingerprint}</code></td></tr>
              <tr><th scope="row">Workflows</th><td>goals {inspected.components.workflows.goals.join(", ") || "none"} · case templates{" "}
                {inspected.components.workflows.case_templates.join(", ") || "none"}</td><td><code>{inspected.components.workflows.fingerprint}</code></td></tr>
              <tr><th scope="row">Agents</th><td data-testid="release-agents">{inspected.components.agents.names.join(", ") || "none"}{" "}
                <span className="badge">{inspected.components.agents.managed === "studio" ? "configured in Studio"
                  : inspected.components.agents.managed === "files" ? "configured by an operator" : "none"}</span></td>
                <td><code>{inspected.components.agents.fingerprint}</code></td></tr>
              <tr><th scope="row">Tools</th><td data-testid="release-tools">{inspected.components.tools.count} declared ·{" "}
                {inspected.components.tools.all_simulated ? "all simulated: no other system is contacted"
                  : `${inspected.components.tools.simulated} simulated, ${inspected.components.tools.other} other (governed by the stage)`}</td>
                <td><code>{inspected.components.tools.fingerprint}</code></td></tr>
              <tr><th scope="row">Governing settings</th><td>{inspected.components.governance.settings.join(", ") || "defaults"}</td>
                <td><code>{inspected.components.governance.fingerprint}</code></td></tr>
            </tbody>
          </table>
        </div>
      )}

      <div className="card">
        <h3>History</h3>
        <ol className="history">
          {state.history.map((h) => (
            <li key={h.seq}><strong>{h.event.replace("_", " ")}</strong> release {h.release} by {h.by} ({h.by_kind})
              {h.reason ? ` — ${h.reason}` : ""} <span className="muted small">{h.at.slice(0, 19).replace("T", " ")}</span></li>
          ))}
        </ol>
      </div>
    </section>
  );
}
