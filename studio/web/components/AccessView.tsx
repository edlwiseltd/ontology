"use client";

// Tenant, workspaces, members and access (Studio increment D). Every rule is the platform's: who may see this
// screen, add a member, propose or approve a grant, confirm one, revoke, or issue a token. What is hidden or
// disabled here is a convenience; the browser tests call the same routes directly and are refused by the platform.

import { useCallback, useEffect, useState } from "react";
import { access, ApiError } from "@/lib/api";
import { DATA_PERMISSIONS, UNRESTRICTED, accessLabel, approvalHint, roleOf, splitList, tokenLabel } from "@/lib/access";
import type { AccessReview, Me, Members, TenantView } from "@/lib/types";

interface Issued { name: string; token: string; expires?: string | null; own?: boolean }

export default function AccessView({ me, onOwnToken }: { me: Me; onOwnToken: (token: string) => void }) {
  const workspace = me.workspace.id;
  const who = `${me.member}@${workspace}`;
  const [view, setView] = useState<Members | null>(null);
  const [review, setReview] = useState<AccessReview | null>(null);
  const [tenant, setTenant] = useState<TenantView | null>(null);
  const [denied, setDenied] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState("");
  const [issued, setIssued] = useState<Issued | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [perms, setPerms] = useState<string[]>(["read"]);
  const [ack, setAck] = useState(false);

  const load = useCallback(async () => {
    setError(""); setDenied("");
    if (me.tenant) {
      try { setTenant(await access.tenant(me.tenant.id)); } catch { setTenant(null); }
    }
    try {
      setView(await access.members(workspace));
      setReview(await access.review(workspace));
    } catch (e) {
      setView(null); setReview(null);
      if (e instanceof ApiError && e.status === 403) setDenied(e.message); else setError((e as Error).message);
    }
  }, [workspace, me.tenant]);

  useEffect(() => { setView(null); setReview(null); setIssued(null); setMessage(""); setPending(""); void load(); }, [load]);

  async function act(done: string, call: () => Promise<unknown>, after?: (out: unknown) => void) {
    setBusy(true); setError(""); setMessage(""); setPending("");
    try {
      const out = await call();
      setMessage(done);
      if (after) after(out);
      await load();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  const you = view?.you;
  const admin = !!you?.may_administer;
  const needReason = !reason.trim();
  const useCases = view?.use_cases ?? [];

  function showToken(out: unknown, own = false) {
    const t = out as { name?: string; token?: string; token_expires_at?: string | null; status?: string; id?: string };
    if (t.token) {
      setIssued({ name: t.name ?? "", token: t.token, expires: t.token_expires_at, own });
      if (own) onOwnToken(t.token);
    } else if (t.status === "pending") {
      setMessage("");
      setPending(`${t.name} holds business data: another person with authority must issue the new token (request ${t.id}). You will not see it.`);
    }
  }

  function addMember(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const form = ev.currentTarget;
    const f = new FormData(form);
    void act(`${String(f.get("name"))} added: give them the token below now`,
             () => access.addMember(workspace, String(f.get("name")), f.get("kind") === "service" ? "service" : "person",
                                    String(f.get("why"))),
             (out) => { showToken(out); form.reset(); });
  }

  function proposeGrant(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const form = ev.currentTarget;
    const f = new FormData(form);
    const unrestricted = perms.includes(UNRESTRICTED);
    void act("", () => access.proposeGrant(workspace, {
      member: String(f.get("member")), use_case: String(f.get("use_case")), permissions: perms,
      roles: splitList(String(f.get("roles") ?? "")), reviewer_roles: splitList(String(f.get("reviewer_roles") ?? "")),
      reason: String(f.get("why")), ...(unrestricted ? { unrestricted: ack } : {}) }),
      () => { setPending("Approval required: the grant takes effect only when another person with authority approves it."); });
  }

  const context = (
    <p className="muted small" data-testid="access-context">
      Tenant <strong>{me.tenant?.name ?? "—"}</strong> <span className="muted">({me.tenant?.id})</span>
      {" · "}Workspace <strong>{me.workspace.name}</strong> <span className="muted">({workspace})</span>
      {" · "}you are <strong>{me.member}</strong>{me.tenant_admin ? ", tenant administrator" : me.workspace_admin ? ", workspace administrator" : ""}
      <span className="source"> · decided by the platform</span>
    </p>
  );

  const tenantCard = tenant && (
    <div className="card">
      <h3>Tenant {tenant.name}</h3>
      <table className="grid" aria-label="Workspaces of the tenant">
        <thead><tr><th>Workspace</th><th>Your role there</th></tr></thead>
        <tbody>
          {tenant.workspaces.map((w) => (
            <tr key={w.id} aria-current={w.id === workspace ? "true" : undefined}>
              <td>{w.name} <span className="muted small">({w.id})</span>{w.id === workspace ? " — shown here" : ""}</td>
              <td>{w.workspace_admin ? "administrator" : w.member ? "member" : "no membership"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {tenant.members && tenant.members.length > 0 && (
        <>
          <h4>Tenant-level identities</h4>
          <ul className="plain small">
            {tenant.members.map((m) => (
              <li key={m.name}>{m.name} — {m.tenant_admin ? "tenant administrator" : "member"} ({m.kind}); workspaces: {(m.workspaces ?? []).join(", ") || "all, as administrator"}</li>
            ))}
          </ul>
          <p className="muted small">Tenant-level identities are defined in the platform configuration.</p>
        </>
      )}
    </div>
  );

  const myToken = (
    <div className="card">
      <h3>Your token</h3>
      <p className="small">{me.token_expires_at ? `Valid until ${me.token_expires_at.slice(0, 10)}.` : "No expiry reported."}{" "}
        <span className="muted">Replacing it ends the current one at once; Studio keeps working with the new one.</span></p>
      <button type="button" className="small" disabled={busy} data-testid="replace-my-token"
              onClick={() => act("Your token was replaced: note the new one below",
                                 () => access.myToken(workspace, reason.trim() || "replaced by its owner"),
                                 (out) => showToken(out, true))}>Replace my token</button>
    </div>
  );

  const tokenBox = issued && (
    <div className="card token-box" role="status" data-testid="issued-token">
      <h3>{issued.own ? "Your new token" : `Token for ${issued.name}`}</h3>
      <p className="small">Shown once and not stored: copy it now{issued.own ? "" : " and give it to the member"}.
        {issued.expires ? ` Valid until ${issued.expires.slice(0, 10)}.` : ""}</p>
      <code className="token" data-testid="token-value">{issued.token}</code>
      <div><button type="button" className="small" onClick={() => setIssued(null)}>I have copied it</button></div>
    </div>
  );

  if (denied) {
    return (
      <section aria-labelledby="acc-title" className="overview">
        <h2 id="acc-title">Access</h2>
        {context}
        <p className="warn" role="alert" data-testid="access-denied">
          You do not have permission to see or change who has access to this workspace ({denied}).
          Workspace administrators and named approvers do. Ask one of them; nothing here was changed.</p>
        {tokenBox}
        {message && <p className="ok" role="status">{message}</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {myToken}
        {tenantCard}
      </section>
    );
  }
  if (!view) return error ? <p className="error" role="alert">{error}</p>
    : <p className="muted" aria-busy="true">Loading members…</p>;

  const waiting = review?.items.filter((i) => i.needs_review) ?? [];

  return (
    <section aria-labelledby="acc-title" className="overview access">
      <h2 id="acc-title">Access</h2>
      {context}
      {view.integrity_problem && <p className="warn" role="alert">{view.integrity_problem}</p>}
      {message && <p className="ok" role="status" data-testid="access-message">{message}</p>}
      {pending && <p className="warn" role="status" data-testid="approval-required">{pending}</p>}
      {error && <p className="error" role="alert" data-testid="access-error">{error}</p>}
      {tokenBox}

      <div className="card">
        <label htmlFor="acc-reason">Reason for a removal, revocation, approval, confirmation or new token</label>
        <input id="acc-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500}
               placeholder="what you checked, or why" />
        <p className="muted small">Every change is recorded with your name and this reason.</p>
      </div>

      <div className="card">
        <h3>Members of {me.workspace.name}</h3>
        <div className="scroll">
          <table className="grid" aria-label="Members">
            <thead><tr><th>Member</th><th>Role</th><th>Token</th>
              {useCases.map((uc) => <th key={uc.id}>{uc.name}</th>)}<th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {view.members.map((m) => (
                <tr key={m.name} data-member={m.name}>
                  <td><strong>{m.name}</strong><div className="muted small">{m.scope === "tenant" ? "tenant identity" : m.source === "api" ? "added here" : "configuration"}</div></td>
                  <td>{roleOf(m)}</td>
                  <td>{tokenLabel(m)}<div className="muted small">issued by {m.token_issued_by ?? "configuration"}</div></td>
                  {useCases.map((uc) => {
                    const eff = m.effective?.[uc.id];
                    const granted = m.use_cases[uc.id];
                    return (
                      <td key={uc.id} data-access={eff?.data_access ?? "none"}>
                        <span className={eff?.data_access === "unrestricted" ? "pill badpill" : ""}>{accessLabel(eff)}</span>
                        {granted && (granted.roles?.length || granted.reviewer_roles?.length) ? (
                          <div className="muted small">roles: {[...(granted.roles ?? []), ...(granted.reviewer_roles ?? []).map((r) => `${r} (reviewer)`)].join(", ")}</div>
                        ) : null}
                        {admin && granted && <div><button type="button" className="small" disabled={busy || needReason}
                          onClick={() => act(`${m.name}'s access to ${uc.name} revoked`,
                                             () => access.revokeGrant(workspace, m.name, uc.id, reason))}>Revoke access</button></div>}
                      </td>
                    );
                  })}
                  <td className="actions">
                    {admin && !m.workspace_admin && m.scope !== "tenant" && (
                      <>
                        <button type="button" className="small" disabled={busy || needReason}
                                onClick={() => act(`New token for ${m.name}`, () => access.newToken(workspace, m.name, reason), showToken)}>New token</button>
                        {m.token === "active" && <button type="button" className="small" disabled={busy || needReason}
                                onClick={() => act(`${m.name}'s token revoked`, () => access.revokeToken(workspace, m.name, reason))}>Revoke token</button>}
                        <button type="button" className="small danger-inline" disabled={busy || needReason}
                                onClick={() => act(`${m.name} removed`, () => access.removeMember(workspace, m.name, reason))}>Remove</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">Administrators administer; they read no business data unless a grant says so.
          Tokens live {view.token_policy?.person_days ?? "—"} days for people, {view.token_policy?.service_days ?? "—"} for service identities.</p>
      </div>

      {admin && (
        <div className="two">
          <form className="card" onSubmit={addMember} aria-labelledby="add-title">
            <h3 id="add-title">Add a member</h3>
            <label htmlFor="m-name">Name</label>
            <input id="m-name" name="name" required pattern="[A-Za-z0-9_.@\-]{1,64}" />
            <label htmlFor="m-kind">Kind</label>
            <select id="m-kind" name="kind"><option value="person">Person</option><option value="service">Service identity</option></select>
            <label htmlFor="m-why">Reason</label>
            <input id="m-why" name="why" required maxLength={500} />
            <button type="submit" disabled={busy}>Add member</button>
            <p className="muted small">A new member has no access until a grant is approved.</p>
          </form>

          <form className="card" onSubmit={proposeGrant} aria-labelledby="grant-title">
            <h3 id="grant-title">Request a grant</h3>
            <label htmlFor="g-member">Member</label>
            <select id="g-member" name="member" required>{view.members.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}</select>
            <label htmlFor="g-uc">Use case</label>
            <select id="g-uc" name="use_case" required>{useCases.map((uc) => <option key={uc.id} value={uc.id}>{uc.name}</option>)}</select>
            <fieldset>
              <legend>Permissions</legend>
              {[...DATA_PERMISSIONS, UNRESTRICTED].map((p) => (
                <label key={p} className="check"><input type="checkbox" checked={perms.includes(p)}
                  onChange={(e) => setPerms(e.target.checked ? [...perms, p] : perms.filter((x) => x !== p))} />
                  {p === UNRESTRICTED ? "admin (unrestricted data access)" : p}</label>
              ))}
            </fieldset>
            {perms.includes(UNRESTRICTED) && (
              <label className="check warn" data-testid="unrestricted-ack"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                I understand that “admin” reads and changes everything in this use case: row and field rules do not apply.</label>
            )}
            <label htmlFor="g-roles">Roles (comma-separated)</label>
            <input id="g-roles" name="roles" />
            <label htmlFor="g-rroles">Reviewer roles (comma-separated)</label>
            <input id="g-rroles" name="reviewer_roles" />
            <label htmlFor="g-why">Reason</label>
            <input id="g-why" name="why" required maxLength={500} />
            <button type="submit" disabled={busy || perms.length === 0}>Request grant</button>
            <p className="muted small">You cannot approve your own request: another person with authority does.</p>
          </form>
        </div>
      )}

      <div className="card">
        <h3>Waiting for approval</h3>
        {view.pending_grants.length === 0 && (view.pending_token_requests ?? []).length === 0
          ? <p className="muted small">Nothing is waiting.</p> : (
          <ul className="plain" aria-label="Pending approvals">
            {view.pending_grants.map((g) => {
              const hint = approvalHint(you, who, g);
              const unrestricted = g.grant.permissions.includes(UNRESTRICTED);
              return (
                <li key={g.id} data-pending={g.id}>
                  <strong>{g.member}</strong> on {g.use_case}: {g.grant.permissions.join(", ")}
                  {unrestricted && <span className="pill badpill"> unrestricted</span>}
                  <div className="muted small">requested by {g.proposed_by} — {g.reason}</div>
                  <div className="row">
                    {hint.offer ? (
                      <button type="button" className="small" disabled={busy || needReason}
                              onClick={() => act(`Grant approved for ${g.member}`,
                                                 () => access.grantDecision(workspace, g.id, "approve", reason, unrestricted))}>
                        {unrestricted ? "Approve unrestricted access" : "Approve"}</button>
                    ) : <span className="muted small" data-testid="approval-hint">{hint.why}</span>}
                    {admin && <button type="button" className="small" disabled={busy || needReason}
                              onClick={() => act("Request withdrawn", () => access.grantDecision(workspace, g.id, "withdraw", reason))}>Withdraw</button>}
                  </div>
                </li>
              );
            })}
            {(view.pending_token_requests ?? []).map((r) => (
              <li key={r.id} data-pending={r.id}>
                New token for <strong>{r.name}</strong>
                <div className="muted small">requested by {r.requested_by} — {r.reason}</div>
                <div className="row">
                  {you?.may_approve && r.requested_by !== who ? (
                    <button type="button" className="small" disabled={busy || needReason}
                            onClick={() => act(`Token issued for ${r.name}`, () => access.issueRequestedToken(workspace, r.id, reason), showToken)}>Issue the token</button>
                  ) : <span className="muted small">another person with authority issues it</span>}
                  {admin && <button type="button" className="small" disabled={busy || needReason}
                            onClick={() => act("Request withdrawn", () => access.withdrawTokenRequest(workspace, r.id, reason))}>Withdraw</button>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {review && (
        <div className="card">
          <h3>Access review</h3>
          <p className="small" data-testid="review-summary">{review.summary.grants} data grants · {review.summary.unrestricted} unrestricted ·{" "}
            <strong>{review.summary.needs_review}</strong> waiting for a person&apos;s review</p>
          {waiting.length > 0 && (
            <ul className="plain" aria-label="Grants to review">
              {waiting.map((i) => (
                <li key={`${i.member}/${i.use_case}`} data-review={`${i.member}/${i.use_case}`}>
                  <strong>{i.member}</strong> on {i.use_case}: {i.permissions.join(", ")} ({i.data_access}), from {i.origin}
                  <div className="row">
                    {you?.may_approve && i.member !== you.member ? (
                      <button type="button" className="small" disabled={busy || needReason}
                              onClick={() => act(`Grant of ${i.member} on ${i.use_case} confirmed`,
                                                 () => access.confirmGrant(workspace, i.member, i.use_case, reason, i.data_access === "unrestricted"))}>
                        {i.data_access === "unrestricted" ? "Confirm unrestricted access" : "Confirm"}</button>
                    ) : <span className="muted small">another person with authority confirms it</span>}
                    {admin && <button type="button" className="small" disabled={busy || needReason}
                              onClick={() => act(`${i.member}'s access to ${i.use_case} revoked`,
                                                 () => access.revokeGrant(workspace, i.member, i.use_case, reason))}>Revoke</button>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {myToken}
      {tenantCard}

      <div className="card">
        <h3>History</h3>
        <ol className="history" aria-label="Administration history">
          {[...view.history].reverse().slice(0, 50).map((h) => (
            <li key={h.seq}><strong>{h.event.replaceAll("_", " ")}</strong> by {h.by}
              {h.reason ? ` — ${h.reason}` : ""} <span className="muted small">{h.at.slice(0, 19).replace("T", " ")}</span></li>
          ))}
        </ol>
      </div>
    </section>
  );
}
