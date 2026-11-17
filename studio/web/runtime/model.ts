// Pure helpers of the application runtime: no network, no DOM. Tested in tests/runtime.test.ts.
import type { AuditEntry, Field, Manifest, May, RecordRow, Related, View } from "./types";
import { VIEW_TYPES } from "./types";

/** View types this renderer has a component for. Anything else is shown as "not supported", never guessed at. */
export const SUPPORTED: ReadonlySet<string> = new Set(VIEW_TYPES);
export const supported = (view: Pick<View, "type">): boolean => SUPPORTED.has(view.type);
export const unsupportedViews = (manifest: Pick<Manifest, "views">): View[] => manifest.views.filter((v) => !supported(v));

/** A value as text. Objects are shown as JSON text; nothing is ever interpreted as markup. */
export function cell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value);
}

export const fieldValue = (row: Pick<RecordRow, "attributes">, field: string): unknown => row.attributes?.[field];

/** Rows of the page already loaded that contain the text. The Engine has no search: this never claims one. */
export function filterLoaded(rows: RecordRow[], query: string, columns: Field[]): RecordRow[] {
  const q = query.trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((r) => r.id.toLowerCase().includes(q)
    || columns.some((c) => cell(fieldValue(r, c.field)).toLowerCase().includes(q)));
}

export function countBy(rows: RecordRow[], field = "status"): [string, number][] {
  const counts = new Map<string, number>();
  for (const r of rows) counts.set(cell(fieldValue(r, field)), (counts.get(cell(fieldValue(r, field))) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** The links of a record that one "related" section of the manifest asks for: recorded links only. */
export function linked(record: Pick<RecordRow, "links">, related: Related): { id: string; type: string }[] {
  return (record.links ?? []).filter((l) => l.kind === related.relationship && l.direction === related.direction
    && l.type === related.entity).map((l) => ({ id: l.id, type: l.type })).sort((a, b) => a.id.localeCompare(b.id));
}

export interface GraphNode { id: string; type: string; x: number; y: number; center: boolean }
export interface GraphEdge { from: string; to: string; label: string }
/** A record and what it is linked to, laid out on a circle. Every edge is a recorded link: none is computed. */
export function graph(record: RecordRow, width = 640, height = 380, most = 24): { nodes: GraphNode[]; edges: GraphEdge[]; omitted: number } {
  const links = (record.links ?? []).slice().sort((a, b) => a.id.localeCompare(b.id));
  const shown = links.slice(0, most);
  const cx = width / 2, cy = height / 2, r = Math.min(width, height) / 2 - 46;
  const seen = new Set<string>();
  const nodes: GraphNode[] = [{ id: record.id, type: record.type, x: cx, y: cy, center: true }];
  const unique = shown.filter((l) => !seen.has(l.id) && seen.add(l.id));
  unique.forEach((l, i) => {
    const angle = (2 * Math.PI * i) / Math.max(unique.length, 1) - Math.PI / 2;
    nodes.push({ id: l.id, type: l.type, x: Math.round(cx + r * Math.cos(angle)), y: Math.round(cy + r * Math.sin(angle)), center: false });
  });
  const edges = shown.map((l) => (l.direction === "out" ? { from: record.id, to: l.id, label: l.kind } : { from: l.id, to: record.id, label: l.kind }));
  return { nodes, edges, omitted: links.length - shown.length };
}

/** What a form holds, shaped for the Engine. Local checks are for the person's comfort; the Engine validates. */
export function formProblems(view: View, values: Record<string, string>): string[] {
  const problems: string[] = [];
  for (const f of view.fields ?? []) {
    const raw = (values[f.field] ?? "").trim();
    if (f.input === "number" && raw && Number.isNaN(Number(raw))) problems.push(`${f.label}: a number`);
    if (f.input === "select" && raw && !(f.options ?? []).includes(raw)) problems.push(`${f.label}: one of ${(f.options ?? []).join(", ")}`);
  }
  return problems;
}
export function formRecord(view: View, values: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of view.fields ?? []) {
    const raw = (values[f.field] ?? "").trim();
    if (raw === "") continue;
    out[f.field] = f.input === "number" ? Number(raw) : f.input === "checkbox" ? raw === "true" : raw;
  }
  return out;
}

const text = (v: unknown): string => (v === null || v === undefined ? "" : Array.isArray(v) ? v.join(", ") : typeof v === "string" ? v : JSON.stringify(v));
const TRACE: Record<string, (d: Record<string, unknown>) => [string, string]> = {
  "run.start": (d) => ["Run started", `${text(d.acting_as)} asked ${text(d.agent)} to reach ${text(d.goal)}`],
  "run.resume": (d) => ["Run resumed", `after ${text(d.previous_status)}`],
  "plan": (d) => ["Plan", (d.plan as string[] | undefined ?? []).join(" → ")],
  "decision": (d) => ["Policy check", `${text(d.action)}: ${text(d.verdict)}${(d.rules as string[] | undefined)?.length ? ` (rules ${text(d.rules)})` : ""}`],
  "governance.deny": (d) => ["Refused by policy", `${text(d.action)}: ${text(d.reasons ?? d.reason)}`],
  "review.requested": (d) => ["A person was asked", `${text(d.action)} → ${text(d.roles)}: ${text(d.reasons)}`],
  "review.decision": (d) => ["A person decided", `${text(d.action)}: ${d.approved ? "approved" : "refused"} by ${text(d.reviewer)}${d.comment ? ` — ${text(d.comment)}` : ""}`],
  "step": (d) => ["Action executed", `${text(d.action)} via ${text(d.tool)} → ${text(d.outcome)}${d.message ? `: ${text(d.message)}` : ""}`],
  "tool.error": (d) => ["Tool failed", `${text(d.action)} via ${text(d.tool)}, attempt ${text(d.attempt)}: ${text(d.error)}`],
  "run.cancelled": (d) => ["Run cancelled", `by ${text(d.by)}: ${text(d.reason)}`],
  "run.end": (d) => ["Run stopped", `status ${text(d.status)}${(d.escalation as { reason?: string } | null)?.reason ? ` — ${(d.escalation as { reason: string }).reason}` : ""}`],
};
/** The Engine's signed chain as readable lines, in order. Entries with no line stay in the chain, uninterpreted. */
export function timeline(entries: AuditEntry[]): { seq: number; at: string; label: string; detail: string }[] {
  return entries.filter((e) => e.event in TRACE).map((e) => {
    const [label, detail] = TRACE[e.event](e.data ?? {});
    return { seq: e.seq, at: String(e.timestamp ?? ""), label, detail };
  });
}

export const RUN_TEXT: Record<string, string> = {
  completed: "Completed", awaiting_review: "Waiting for a person's decision", escalated: "Stopped by the Engine",
  cancelled: "Cancelled", deferred: "Deferred: a tool failed, a retry is due", paused: "Paused", blocked: "Blocked by the rules" };
/** One sentence on how a run ended. A refusal by policy is called a refusal, with the Engine's own reason. */
export function outcome(run: { status: string; escalation?: { reason: string; details?: string[] } | null }): string {
  const details = (run.escalation?.details ?? []).join("; ");
  if (run.status === "escalated" && /prohibited/.test(details)) return `Refused by policy: ${details}`;
  if (run.status === "escalated") return `Stopped: ${run.escalation?.reason ?? "no way to the goal within the rules"}${details ? ` (${details})` : ""}`;
  if (run.status === "awaiting_review") return `Waiting for a person: ${run.escalation?.reason ?? ""}${details ? ` (${details})` : ""}`;
  return RUN_TEXT[run.status] ?? run.status;
}

/** The short label of a run: a refusal by policy is named as one wherever the Engine's reason is known. */
export function runLabel(run: { status: string; escalation?: { reason: string; details?: string[] } | null }): string {
  if (run.status === "escalated" && /prohibited/.test((run.escalation?.details ?? []).join(" "))) return "Refused by policy";
  return RUN_TEXT[run.status] ?? run.status;
}

export const short = (fingerprint: string | undefined): string => (fingerprint ?? "").slice(0, 12);
export const viewFor = (manifest: Manifest, type: string, entity: string): View | undefined =>
  manifest.views.find((v) => v.type === type && v.entity === entity);

// -- the menu, grouped by what a screen is for. The groups come from the view types of the schema, never from a name.
export const NAV_GROUPS: [string, string[]][] = [
  ["Overview", ["DashboardView"]], ["Work", ["WorkflowView", "ApprovalInboxView"]],
  ["Records", ["EntityListView", "EntityDetailView", "RelationshipView", "RecordFormView"]], ["Evidence", ["AuditTimelineView"]]];
/** A menu with more entries than this gets a box to find a screen by its label. */
export const NAV_FILTER_FROM = 9;
export function groupNavigation(navigation: Manifest["navigation"], views: { id: string; type: string }[], query = ""):
    { label: string; items: Manifest["navigation"] }[] {
  const type = Object.fromEntries(views.map((v) => [v.id, v.type]));
  const q = query.trim().toLowerCase();
  return NAV_GROUPS.map(([label, types]) => ({ label,
    items: navigation.filter((n) => types.includes(type[n.view]) && (!q || n.label.toLowerCase().includes(q))) }))
    .filter((g) => g.items.length > 0);
}

// -- what this caller can and cannot do, in words. The Engine's answer ("you.may") is the only source.
const CAPABILITIES: [keyof May, string, string][] = [
  ["read_records", "Read records, within the rules of the model", "needs the read permission"],
  ["start_runs", "Ask the solution to handle a record", "needs the run permission, in a stage that allows runs"],
  ["decide_reviews", "Decide reviews addressed to your reviewer roles", "needs the review permission, held by a person"],
  ["read_audit", "Read the audit trail of a request", "needs the audit permission"],
  ["write_records", "Create or change records", "needs the unrestricted data permission: no narrower one exists (owner decision D24)"]];
export function capabilities(may: May): { can: string[]; cannot: { what: string; why: string }[] } {
  return { can: CAPABILITIES.filter(([k]) => may[k]).map(([, what]) => what),
           cannot: CAPABILITIES.filter(([k]) => !may[k]).map(([, what, why]) => ({ what, why })) };
}

