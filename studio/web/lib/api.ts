// The typed client Studio uses. Same origin only: requests go to Studio's relay (lib/forward.ts), which forwards
// them to the platform. The token stays in this browser tab (sessionStorage) and is sent as a bearer token, so
// there is no cookie to forge. UI-side checks are advisory: every rule is enforced by the platform and the engine.

import type { AccessReview, ActivationResult, AiView, ApiErrorBody, CheckResult, Draft, DraftSimulation, GrantProposal,
  IssuedToken, Me, Members, ModelDocument, MoveResult, OntologySummary, Proposal, ProposalList, Published, Readiness,
  RecoveryDrill, Release, ReleaseState, Restored, SampleData, Solution, SolutionDraft, Stage, Template, TenantView,
  TokenIssuedOrRequested, UseCase, ValidationResult } from "./types";
// (run shapes are hand-typed in lib/runs.ts: the engine's run routes answer open objects)
import type { EngineMe, ObjectRow, ReviewView, RunAudit, RunRow, RunView } from "./runs";
import type { Manifest } from "@/runtime/types";

export class ApiError extends Error {
  constructor(public status: number, message: string, public data: Record<string, unknown> = {}) {
    super(message);
  }
}

const TOKEN_KEY = "autology-studio-token";
let memoryToken: string | null = null;

export function getToken(): string | null {
  try { return sessionStorage.getItem(TOKEN_KEY) ?? memoryToken; } catch { return memoryToken; }
}

export function setToken(token: string | null): void {
  memoryToken = token;
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token); else sessionStorage.removeItem(TOKEN_KEY);
  } catch { /* memory only */ }
}

export async function request<T>(method: "GET" | "POST", path: string, body?: unknown,
                                 fetcher: typeof fetch = fetch): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${getToken() ?? ""}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetcher(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body),
                                    redirect: "error", cache: "no-store" });
  let data: Record<string, unknown> = {};
  try { data = await res.json(); } catch { data = { error: "unexpected answer from the platform" }; }
  if (!res.ok) throw new ApiError(res.status, errorMessage(data, res.status), errorDetails(data));
  return data as T;
}

// API v1 errors are {error: {status, code, message, details}}; anything else (a proxy, an old server) is shown as is.
// ApiError.data carries the details (a conflict's current revision, a refused move's checks).
export function errorDetails(data: Record<string, unknown>): Record<string, unknown> {
  const e = (data as Partial<ApiErrorBody>).error;
  if (e && typeof e === "object") return { code: e.code, ...(e.details ?? {}) };
  return data;
}

export function errorMessage(data: Record<string, unknown>, status: number): string {
  const e = (data as Partial<ApiErrorBody>).error;
  if (e && typeof e === "object" && typeof e.message === "string") return e.message;
  if (typeof data.error === "string") return data.error;
  return `HTTP ${status}`;
}

const ws = (id: string) => `/platform/v1/workspaces/${encodeURIComponent(id)}/use-cases`;
const adm = (id: string) => `/platform/v1/workspaces/${encodeURIComponent(id)}`;
const enc = encodeURIComponent;

export interface GrantRequest {
  member: string; use_case: string; permissions: string[]; roles: string[]; reviewer_roles: string[];
  reason: string; unrestricted?: boolean;
}

// Access administration (ADM-1, IAM-1, GAP-030, sprint B). Studio only asks: who may see, add, propose, approve,
// confirm, revoke or re-key is decided by the platform on every call, whatever a screen shows or hides.
export const access = {
  tenant: (tenant: string) => request<TenantView>("GET", `/platform/v1/tenants/${enc(tenant)}`),
  members: (w: string) => request<Members>("GET", `${adm(w)}/members`),
  review: (w: string) => request<AccessReview>("GET", `${adm(w)}/access-review`),
  addMember: (w: string, name: string, kind: "person" | "service", reason: string) =>
    request<IssuedToken>("POST", `${adm(w)}/members`, { name, kind, reason }),
  removeMember: (w: string, name: string, reason: string) =>
    request<Members>("POST", `${adm(w)}/members/${enc(name)}/remove`, { reason }),
  newToken: (w: string, name: string, reason: string) =>
    request<TokenIssuedOrRequested>("POST", `${adm(w)}/members/${enc(name)}/token`, { reason }),
  revokeToken: (w: string, name: string, reason: string) =>
    request<Members>("POST", `${adm(w)}/members/${enc(name)}/revoke-token`, { reason }),
  revokeGrant: (w: string, name: string, use_case: string, reason: string) =>
    request<Members>("POST", `${adm(w)}/members/${enc(name)}/revoke`, { use_case, reason }),
  confirmGrant: (w: string, name: string, use_case: string, reason: string, unrestricted: boolean) =>
    request<AccessReview>("POST", `${adm(w)}/members/${enc(name)}/confirm-grant`,
                          { use_case, reason, ...(unrestricted ? { unrestricted: true } : {}) }),
  proposeGrant: (w: string, grant: GrantRequest) => request<GrantProposal>("POST", `${adm(w)}/grants`, grant),
  grantDecision: (w: string, id: string, action: "approve" | "withdraw", reason: string, unrestricted = false) =>
    request<Members>("POST", `${adm(w)}/grants/${enc(id)}/${action}`,
                     { reason, ...(unrestricted ? { unrestricted: true } : {}) }),
  issueRequestedToken: (w: string, id: string, reason: string) =>
    request<IssuedToken>("POST", `${adm(w)}/token-requests/${enc(id)}/approve`, { reason }),
  withdrawTokenRequest: (w: string, id: string, reason: string) =>
    request<Members>("POST", `${adm(w)}/token-requests/${enc(id)}/withdraw`, { reason }),
  myToken: (w: string, reason: string) => request<IssuedToken>("POST", `${adm(w)}/my-token`, { reason }),
};

export const api = {
  me: (workspace?: string) =>
    request<Me>("GET", workspace ? `/platform/v1/me?workspace=${enc(workspace)}` : "/platform/v1/me"),
  useCases: (w: string) => request<{ items: UseCase[] }>("GET", ws(w)),
  useCase: (w: string, uc: string) => request<UseCase>("GET", `${ws(w)}/${encodeURIComponent(uc)}`),
  checks: (w: string, uc: string, to: Stage) =>
    request<CheckResult>("GET", `${ws(w)}/${encodeURIComponent(uc)}/checks?to=${to}`),
  move: (w: string, uc: string, to: Stage, reason: string) =>
    request<MoveResult>("POST", `${ws(w)}/${encodeURIComponent(uc)}/stage`, { to, reason }),
  templates: () => request<{ items: Template[] }>("GET", "/platform/v1/templates"),
  createUseCase: (w: string, id: string, name: string, template: string) =>
    request<UseCase>("POST", ws(w), { id, name, template }),
  ontology: (path: string) => request<OntologySummary>("GET", `${path}/api/v1/ontology`),
  // model design: drafts never change what runs; the engine validates and decides
  draft: (path: string) => request<Draft>("GET", `${path}/api/v1/model/draft`),
  // origin: the stored proposal revision the model was saved from; the engine checks it and records it with the draft
  saveDraft: (path: string, document: ModelDocument, expected_revision: number, note: string,
              origin?: { proposal: string; revision: number }) =>
    request<Draft>("POST", `${path}/api/v1/model/draft`, { document, expected_revision, note, ...(origin ? { origin } : {}) }),
  validate: (path: string, document: ModelDocument) =>
    request<ValidationResult>("POST", `${path}/api/v1/model/validate`, { document }),
  // releases (REL-1a, STU-6): the platform decides who may propose, approve and activate
  releases: (w: string, uc: string) => request<ReleaseState>("GET", `${ws(w)}/${encodeURIComponent(uc)}/releases`),
  // one release: what it contains, part by part, and the engine's verdict on its coherence
  release: (w: string, uc: string, n: number) => request<Release>("GET", `${ws(w)}/${encodeURIComponent(uc)}/releases/${n}`),
  proposeRelease: (w: string, uc: string, note: string) =>
    request<Release>("POST", `${ws(w)}/${encodeURIComponent(uc)}/releases`, { note }),
  releaseAction: (w: string, uc: string, n: number, action: "approve" | "revoke", reason: string) =>
    request<Release>("POST", `${ws(w)}/${encodeURIComponent(uc)}/releases/${n}/${action}`, { reason }),
  activateRelease: (w: string, uc: string, n: number, reason: string) =>
    request<ActivationResult>("POST", `${ws(w)}/${encodeURIComponent(uc)}/releases/${n}/activate`, { reason }),
  restoreRelease: (w: string, uc: string, n: number, reason: string) =>
    request<Restored>("POST", `${ws(w)}/${encodeURIComponent(uc)}/releases/${n}/restore`, { reason }),
  publishDraft: (w: string, uc: string, revision: number, reason: string) =>
    request<Published>("POST", `${ws(w)}/${encodeURIComponent(uc)}/publish-draft`, { revision, reason }),
  propose: (path: string, brief: string, document: ModelDocument) =>
    request<Proposal>("POST", `${path}/api/v1/architect/proposals`, { brief, document }),
  // the workspace's AI provider policy, the owner's authorisation and spending (read-only here)
  aiView: (w: string) => request<AiView>("GET", `${adm(w)}/ai`),
  // sample records: loaded only on an administrator's explicit, recorded request; a release never loads data
  sampleData: (w: string, uc: string) => request<SampleData>("GET", `${ws(w)}/${encodeURIComponent(uc)}/sample-data`),
  loadSampleData: (w: string, uc: string, reason: string) =>
    request<SampleData>("POST", `${ws(w)}/${encodeURIComponent(uc)}/sample-data`, { reason }),
  // a recovery rehearsal (backup, verify, restore into a scratch folder, load): evidence for readiness
  recoveryDrill: (w: string, reason: string) => request<RecoveryDrill>("POST", `${adm(w)}/recovery-drill`, { reason }),
  // readiness of one configuration: what runs ("active"), the saved draft ("draft") or a release ("release:<n>")
  readiness: (w: string, uc: string, target: "pilot" | "production", of: string = "active") =>
    request<Readiness>("GET", `${ws(w)}/${encodeURIComponent(uc)}/readiness?target=${target}&of=${enc(of)}`),
};

// The executable configuration of a draft (agents, simulated tools, sample records). The engine validates,
// compiles and stores it; saving changes nothing that runs.
export const configuration = {
  draft: (path: string) => request<SolutionDraft>("GET", `${path}/api/v1/solution/draft`),
  validate: (path: string, solution: Solution | null) =>
    request<SolutionDraft>("POST", `${path}/api/v1/solution/validate`, { solution }),
  suggest: (path: string, proposal?: string) =>
    request<SolutionDraft>("POST", `${path}/api/v1/solution/suggest`, proposal ? { proposal } : {}),
  save: (path: string, solution: Solution | null, expected_revision: number, note: string) =>
    request<SolutionDraft>("POST", `${path}/api/v1/solution/draft`, { solution, expected_revision, note }),
};

// Stored simulation runs: the engine's own run, review and audit routes. Starting needs `run`, deciding a review
// needs `review` and the reviewer role, the audit chain needs `audit`; the engine refuses everything else.
export const runs = {
  me: (path: string) => request<EngineMe>("GET", `${path}/api/v1/me`),
  objects: (path: string, type: string) =>
    request<{ items: ObjectRow[] }>("GET", `${path}/api/v1/objects?type=${enc(type)}&limit=100`),
  // create or change one record: the engine checks the permission, the write rules and the revision that was read
  upsert: (path: string, body: { type: string; id: string; attributes: Record<string, unknown>; expected_revision: number;
                                 justification?: string }) => request<ObjectRow>("POST", `${path}/api/v1/objects`, body),
  list: (path: string) => request<{ items: RunRow[] }>("GET", `${path}/api/v1/runs?limit=50`),
  get: (path: string, id: string) => request<RunView>("GET", `${path}/api/v1/runs/${enc(id)}`),
  start: (path: string, body: { case_template: string; root: string; agent?: string; goal?: string }) =>
    request<RunView>("POST", `${path}/api/v1/runs`, body),
  audit: (path: string, id: string) => request<RunAudit>("GET", `${path}/api/v1/runs/${enc(id)}/audit`),
  reviews: (path: string) => request<{ items: ReviewView[] }>("GET", `${path}/api/v1/reviews?status=pending`),
  decide: (path: string, review: string, approved: boolean, comment: string) =>
    request<RunView>("POST", `${path}/api/v1/reviews/${enc(review)}/decision`, { approved, comment }),
  resume: (path: string, id: string) => request<RunView>("POST", `${path}/api/v1/runs/${enc(id)}/resume`, { force: true }),
  cancel: (path: string, id: string, reason: string) =>
    request<RunView>("POST", `${path}/api/v1/runs/${enc(id)}/cancel`, { reason }),
};

// The Application Builder: manifests of what runs. The engine generates, validates and stores; Studio arranges.
export interface AppCheck { valid: boolean; problems: { path: string; message: string }[]; digest?: string | null }
export interface AppDraft { revision: number; manifest: Manifest | null; validation: AppCheck | null; author?: string | null;
  at?: string | null; note?: string | null; history: { revision: number; author: string; at: string; note: string; configuration: string }[];
  running: Manifest["binding"]; saved?: boolean }
export const application = {
  draft: (path: string) => request<AppDraft>("GET", `${path}/api/v1/application/draft`),
  generate: (path: string) => request<{ manifest: Manifest; validation: AppCheck; generator: { kind: string; ai: boolean; note: string } }>(
    "POST", `${path}/api/v1/application/generate`, {}),
  validate: (path: string, manifest: Manifest) =>
    request<{ validation: AppCheck }>("POST", `${path}/api/v1/application/validate`, { manifest }),
  save: (path: string, manifest: Manifest, expected_revision: number, note: string) =>
    request<AppDraft>("POST", `${path}/api/v1/application/draft`, { manifest, expected_revision, note }),
};

export interface SimulatedDecision { action: string; approved: boolean; as?: string }

// The architect through the engine's AI gateway, and the dry run of a draft. Studio only asks and shows: the
// engine validates every proposed item, stores each revision, and decides what a simulation may do.
export const architect = {
  list: (path: string) => request<ProposalList>("GET", `${path}/api/v1/architect/proposals`),
  // a stored proposal, read again: the latest revision or a named one. Nothing is asked of any model
  get: (path: string, id: string, revision?: number) =>
    request<Proposal>("GET", `${path}/api/v1/architect/proposals/${enc(id)}${revision ? `?revision=${revision}` : ""}`),
  propose: (path: string, brief: string, document: ModelDocument) =>
    request<Proposal>("POST", `${path}/api/v1/architect/proposals`, { generator: "model", brief, document }),
  // answers to its questions and, optionally, what the person wants changed, in words (data for the architect)
  revise: (path: string, id: string, answers: { id: string; answer: string }[], document: ModelDocument, feedback = "") =>
    request<Proposal>("POST", `${path}/api/v1/architect/proposals`,
                      { generator: "model", revises: id, answers, document, ...(feedback.trim() ? { feedback } : {}) }),
  decide: (path: string, id: string, revision: number, accepted: string[], rejected: string[], note: string) =>
    request<Proposal>("POST", `${path}/api/v1/architect/proposals/${enc(id)}/decision`,
                      { revision, accepted, rejected, note }),
  simulate: (path: string, document: ModelDocument, approvals: SimulatedDecision[]) =>
    request<DraftSimulation>("POST", `${path}/api/v1/model/draft/simulate`, { document, approvals }),
};
