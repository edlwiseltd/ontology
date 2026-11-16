// Stored simulation runs of a use case: shapes of the engine's answers and pure helpers to present them. The
// engine starts, pauses, resumes, cancels and audits runs and decides who may see or decide what; nothing here
// does. A run on simulated tools is never presented as proof that a real system changed.

// Shapes come from the engine's published contract (lib/generated/engine.ts), not from this file.
import type { AuditEntry, Review, Run, RunAudit, RunRow, RunStep } from "./types";

export type { AuditEntry, RunAudit, RunRow, RunStep };
export type RunView = Run;
export type ReviewView = Review;
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
  const by = s.tool ? `${s.tool}${s.environment ? ` (${s.environment})` : ""}` : "no tool";
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

const text = (v: unknown): string => (v === null || v === undefined ? "" : Array.isArray(v) ? v.join(", ") : typeof v === "string" ? v : JSON.stringify(v));

// the entries of the signed chain that tell the story; the others (idempotency keys, raw tool calls) stay in the chain
const TRACE: Record<string, (d: Record<string, unknown>) => [string, string]> = {
  "run.start": (d) => ["run started", `${text(d.acting_as)} started ${text(d.agent)} for ${text(d.goal)} on ${text(d.ontology)}`],
  "run.resume": (d) => ["run resumed", `after ${text(d.previous_status)}`],
  "plan": (d) => ["plan", (d.plan as string[] | undefined ?? []).join(" → ")],
  "decision": (d) => ["policy check", `${text(d.action)}: ${text(d.verdict)}${(d.rules as string[] | undefined)?.length ? ` (rules ${text(d.rules)})` : ""}`],
  "governance.deny": (d) => ["refused by policy", `${text(d.action)}: ${text(d.reasons ?? d.reason)}`],
  "review.requested": (d) => ["review requested", `${text(d.action)} → ${text(d.roles)}: ${text(d.reasons)}`],
  "review.decision": (d) => ["review decided", `${text(d.action)}: ${d.approved ? "approved" : "refused"} by ${text(d.reviewer)}${d.comment ? ` — ${text(d.comment)}` : ""}`],
  "step": (d) => ["action executed", `${text(d.action)} via ${text(d.tool)} → ${text(d.outcome)}${d.message ? `: ${text(d.message)}` : ""}`],
  "tool.error": (d) => ["tool failed", `${text(d.action)} via ${text(d.tool)}, attempt ${text(d.attempt)}: ${text(d.error)}`],
  "run.cancelled": (d) => ["run cancelled", `by ${text(d.by)}: ${text(d.reason)}`],
  "integrity.violation": (d) => ["integrity violation", text(d.reason)],
  "run.end": (d) => ["run stopped", `status ${text(d.status)}${(d.escalation as { reason?: string } | null)?.reason ? ` — ${(d.escalation as { reason: string }).reason}` : ""}`],
};

/** The audit chain as a decision trace, in order: what was planned, checked, decided and executed. */
export function trace(entries: AuditEntry[]): { seq: number; at: string; label: string; detail: string }[] {
  return entries.filter((e) => e.event in TRACE).map((e) => {
    const [label, detail] = TRACE[e.event](e.data ?? {});
    return { seq: e.seq, at: String(e.timestamp ?? ""), label, detail };
  });
}
