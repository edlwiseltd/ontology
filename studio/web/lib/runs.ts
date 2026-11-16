// Stored simulation runs of a use case: shapes of the engine's answers and pure helpers to present them. The
// engine starts, pauses, resumes, cancels and audits runs and decides who may see or decide what; nothing here
// does. A run on simulated tools is never presented as proof that a real system changed.

export interface RunStep { index: number; action: string; verdict: string; outcome: string | null; executed_by: string | null;
  reviewer: string | null; message?: string | null; explanation?: string | null; environment?: string | null }
export interface RunEscalation { reason: string; to: string; action: string | null; details: string[] }
export interface RunView { run_id: string; case_id: string; goal: string; status: string; steps: RunStep[];
  escalation: RunEscalation | null; costs: Record<string, number>; audit_verified: boolean;
  state: Record<string, unknown>; pending_review: string | null; configuration?: string; agent?: string | null;
  started_by?: string | null; simulated?: boolean; effects?: string; hidden?: boolean; detail?: string }
export interface RunRow { run_id: string; case_id: string; goal: string; agent: string | null; status: string;
  created_at: string; updated_at: string; started_by: string | null }
export interface ReviewView { review_id: string; run_id: string; action: string; reviewers: string[]; status: string;
  created_at: string; request: { description?: string; reasons?: string[]; rule_ids?: string[]; facts?: Record<string, unknown>;
                                 explanation?: string } }
export interface AuditEntry { seq: number; timestamp: string; event: string; data: Record<string, unknown>; hash: string }
export interface RunAudit { run_id: string; verified: boolean; entries: AuditEntry[] }
export interface EngineMe { name: string; permissions: string[]; roles?: string[]; reviewer_roles?: string[]; kind?: string }
export interface ObjectRow { id: string; type: string; attributes: Record<string, unknown>; revision: number }

export const STATUS_TEXT: Record<string, string> = {
  completed: "completed", awaiting_review: "waiting for a person", deferred: "deferred: a tool failed, a retry is due",
  paused: "paused", escalated: "escalated to a person", blocked: "blocked by the rules", cancelled: "cancelled",
  suspended: "suspended", uncertain: "an external call is unresolved", pending_confirmation: "waiting for confirmation" };

export const OPEN = new Set(["awaiting_review", "deferred", "paused"]);
/** A run a person may still stop (the engine decides; this only hides a button that would be refused). */
export const cancellable = (status: string): boolean => OPEN.has(status);
export const resumable = (status: string): boolean => status === "deferred" || status === "paused";
export const statusClass = (status: string): string =>
  status === "completed" ? "okpill" : status === "awaiting_review" || status === "deferred" || status === "paused" ? "warnpill" : "";

/** What a step did, in one line: who or what executed it, and that a simulated tool reached nothing. */
export function stepLine(s: RunStep): string {
  const by = s.executed_by ? `${s.executed_by}${s.environment ? ` (${s.environment})` : ""}` : "no tool";
  const decided = s.reviewer ? ` · decided by ${s.reviewer}` : "";
  return `${s.verdict}${s.outcome ? ` → ${s.outcome}` : ""} · ${by}${decided}`;
}

/** The release a run was started on: the one whose fingerprint is the run's configuration. */
export function releaseOf(run: Pick<RunView, "configuration">, releases: { number: number; fingerprint: string }[]): number | null {
  return releases.find((r) => r.fingerprint === run.configuration)?.number ?? null;
}

/** May this identity decide this review? (The engine checks again; a requester never decides their own run.) */
export function mayDecide(me: EngineMe | null, review: ReviewView, run: Pick<RunView, "started_by">): boolean {
  if (!me || !me.permissions.includes("review") || me.kind === "service") return false;
  if (run.started_by === me.name) return false;
  return me.permissions.includes("admin") || (me.reviewer_roles ?? []).some((r) => review.reviewers.includes(r));
}

/** Audit events grouped for a decision trace: what was checked, decided, executed, in order. */
export function trace(entries: AuditEntry[]): { seq: number; at: string; label: string; detail: string }[] {
  const text = (v: unknown) => (v === null || v === undefined ? "" : typeof v === "string" ? v : JSON.stringify(v));
  return entries.map((e) => {
    const d = e.data ?? {};
    const detail = e.event === "governance.decision" ? `${text(d.action)}: ${text(d.verdict)}${d.reasons ? ` (${text(d.reasons)})` : ""}`
      : e.event === "review.requested" ? `${text(d.action)} → ${text(d.reviewers)}`
      : e.event === "review.decision" ? `${text(d.action)}: ${d.approved ? "approved" : "declined"} by ${text(d.reviewer)}`
      : e.event === "run.cancelled" ? `by ${text(d.by)}: ${text(d.reason)}`
      : e.event === "run.end" ? `status ${text(d.status)}`
      : e.event.startsWith("tool.") || e.event === "action.executed" ? `${text(d.action)}${d.tool ? ` via ${text(d.tool)}` : ""}${d.outcome ? ` → ${text(d.outcome)}` : ""}${d.error ? ` — ${text(d.error)}` : ""}`
      : text(d.action ?? d.goal ?? d.reason ?? "");
    return { seq: e.seq, at: e.timestamp, label: e.event, detail };
  });
}
