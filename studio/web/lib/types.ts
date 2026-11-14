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

// -- model design (increment 2) -----------------------------------------------------------------------------
export type ModelDocument = Record<string, any>;  // an ontology document, as the engine's strict schema defines it

export interface Problem { path: string; message: string; node?: string; field?: string | null; edge?: number;
                           section?: string; name?: string; index?: number }
export interface Validation { valid: boolean; problems: Problem[]; note?: string; ref?: string; fingerprint?: string;
                              summary?: Record<string, number> }
export interface Question { id: string; kind: string; severity: "high" | "medium" | "low"; question: string; why: string;
                            evidence: string; node?: string; action?: string; rule?: number }
export interface Draft { revision: number; document: ModelDocument; author: string | null; at: string | null; note: string;
                         active: { ref: string; fingerprint: string }; validation: Validation; questions: Question[] }
export interface ProposalItem { id: string; kind: "entity" | "relationship" | "action" | "rule"; name: string | null;
                                value: any; rationale: string; status: "provisional";
                                provenance: { generator: string; blueprint?: string; ai: boolean; matched_terms: string[] } }
export interface Proposal { generator: string; ai: boolean; blueprint?: { id: string; name: string };
                            matched_terms?: string[]; items: ProposalItem[]; message: string }
