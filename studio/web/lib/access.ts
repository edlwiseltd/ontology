// Words for what the platform reports about members and grants. Nothing here decides anything: these functions
// turn the platform's answers into labels, and into hints about which buttons are worth showing. The platform
// checks every action again.

import type { GrantProposal, Members, WorkspaceMember } from "./types";

export const DATA_PERMISSIONS = ["read", "run", "review", "audit", "ingest", "reconcile"] as const;
export const UNRESTRICTED = "admin";

export function roleOf(m: Pick<WorkspaceMember, "workspace_admin" | "tenant_admin" | "approver" | "kind">): string {
  const roles: string[] = [];
  if (m.tenant_admin) roles.push("tenant administrator");
  else if (m.workspace_admin) roles.push("workspace administrator");
  if (m.approver) roles.push("approver");
  if (roles.length === 0) roles.push("member");
  return roles.join(", ") + (m.kind === "service" ? " (service identity)" : "");
}

export function accessLabel(effective: { permissions: string[]; data_access: string } | undefined): string {
  if (!effective || effective.permissions.length === 0) return "no access";
  const perms = effective.permissions.join(", ");
  if (effective.data_access === "unrestricted") return `${perms} — unrestricted data access`;
  if (effective.data_access === "scoped") return `${perms} — data within row and field rules`;
  return `${perms} — administration only, no business data`;
}

export function tokenLabel(m: Pick<WorkspaceMember, "token" | "token_expires_at">): string {
  if (m.token === "none") return "no token (revoked)";
  if (m.token === "revoked") return "revoked";
  const until = m.token_expires_at ? m.token_expires_at.slice(0, 10) : "";
  if (m.token === "expired") return `expired ${until}`.trim();
  return until ? `valid until ${until}` : "valid";
}

// Why a second person is needed, in the platform's own terms (it refuses the same cases with 403).
export function approvalHint(you: Members["you"], who: string, proposal: Pick<GrantProposal, "proposed_by" | "member">):
    { offer: boolean; why: string } {
  if (!you?.may_approve) return { offer: false, why: "needs a person with authority (administrator or approver)" };
  if (proposal.proposed_by === who) return { offer: false, why: "you proposed it: another person with authority must approve" };
  if (proposal.member === you.member) return { offer: false, why: "it is for you: another person with authority must approve" };
  return { offer: true, why: "" };
}

export function splitList(text: string): string[] {
  return text.split(",").map((part) => part.trim()).filter(Boolean);
}
