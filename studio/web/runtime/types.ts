// Shapes the application runtime reads. A manifest is data validated by the Engine (autology/appspec.py); nothing
// in it is code, and nothing in it is a permission.

export type Basis = "ontology" | "configuration" | "default" | "confirmed" | "unresolved";
export const VIEW_TYPES = ["DashboardView", "EntityListView", "EntityDetailView", "RelationshipView", "RecordFormView",
  "WorkflowView", "ApprovalInboxView", "AuditTimelineView"] as const;
export type ViewType = (typeof VIEW_TYPES)[number];

export interface Field { field: string; label: string; basis: Basis; input?: string; options?: string[] }
export interface Related { relationship: string; direction: "out" | "in"; entity: string; label: string; basis: Basis }
export interface ActionSpec { action: string; label: string; rules: string[]; basis: Basis }
export interface View {
  id: string; type: string; title: string; basis: Basis; entity?: string;
  columns?: Field[]; title_field?: string; page_size?: number; fields?: Field[]; related?: Related[];
  case_template?: string; agent?: string; states?: string[]; actions?: ActionSpec[]; rules?: string[];
  tiles?: { entity: string; label: string; basis: Basis }[];
  available?: boolean; unavailable_because?: string;
}
export interface Manifest {
  manifest_version: number; id: string; title: string; description?: string;
  binding: { model: string; model_fingerprint: string; configuration: string; engine_api: string; workspace?: string; use_case?: string };
  roles: string[]; navigation: { view: string; label: string; basis: Basis }[]; views: View[];
  unavailable: { feature: string; reason: string }[];
  presentation: { accent: string; density: string };
}
export interface May { read_records: boolean; start_runs: boolean; decide_reviews: boolean; read_audit: boolean; write_records: boolean }
export interface Application {
  manifest: Manifest; revision: number; digest: string; status: string; stage: string | null; runs_refused: string | null;
  production: boolean; running: Manifest["binding"]; you: { name: string; kind: string; permissions: string[]; may: May };
}
export interface RecordRow { id: string; type: string; attributes: Record<string, unknown>; revision?: number;
  links?: { kind: string; direction: "out" | "in"; id: string; type: string }[] }
export interface RunStep { index?: number; action: string; verdict: string; outcome?: string | null; tool?: string | null;
  environment?: string | null; reviewer?: string | null; message?: string | null }
export interface Run { run_id: string; case_id: string; status: string; agent?: string | null; started_by?: string | null;
  configuration?: string; simulated?: boolean; steps?: RunStep[]; pending_review?: string | null;
  escalation?: { reason: string; to?: string | null; action?: string | null; details?: string[] } | null; hidden?: boolean }
export interface Review { review_id: string; run_id: string; action: string; reviewers: string[]; status: string;
  request: { case_id?: string; action?: string; description?: string | null; reasons?: string[]; rule_ids?: string[] } }
export interface AuditEntry { seq: number; timestamp?: string | number; event: string; data: Record<string, unknown> }
export interface RuleInfo { id: string; kind: string; description: string }

/** How the runtime is being shown. Only "simulation" talks to the Engine for runs and reviews. */
export type Mode = "configuration" | "synthetic" | "simulation";
export const MODE_LABEL: Record<Mode, string> = {
  configuration: "Configuration preview: the screens as designed, without records",
  synthetic: "Synthetic-data preview: invented records, read only",
  simulation: "Engine-backed simulation: synthetic records, simulated tools",
};
