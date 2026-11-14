// Shapes returned by the platform router and the engine. The engine contract
// is published at /api/openapi.json; the platform's own routes are not in it yet (see the API contract matrix).

export type Stage = "draft" | "simulation" | "pilot" | "production";

export interface Me {
  workspace: { id: string; name: string };
  member: string;
  workspace_admin: boolean;
  use_cases: { id: string; name: string; ontology: string; permissions: string[]; stage: Stage; path: string }[];
}

export interface StageEvent {
  seq: number; from_stage: Stage; to_stage: Stage; by: string; reason: string; fingerprint: string; at: string;
  checks: Check[];
}

export interface UseCase {
  id: string; name: string; origin: "configuration" | "template"; template: string | null; ontology: string;
  fingerprint: string; path: string; permissions: string[]; stage: Stage; effective_stage: Stage; stale: boolean;
  integrity_problem: string | null; stages: Stage[]; history?: StageEvent[];
}

export interface Check { id: string; passed: boolean; detail: string }

export interface CheckResult { from: Stage; to: Stage; forward: boolean; checks: Check[]; allowed: boolean }

export interface Template { id: string; name: string; description: string }

export interface OntologySummary {
  ref: string;
  fingerprint: string;
  description: string;
  entities: Record<string, { states: string[]; multiple: boolean; aliases: string[]; attributes: Record<string, string> }>;
  relationships: { source: string; target: string; kind: string; cardinality: string }[];
  actions: Record<string, { description: string }>;
  rules: { id: string; kind: string; description: string }[];
}
