// The typed client Studio uses. Same origin only: requests go to Studio's relay (lib/forward.ts), which forwards
// them to the platform. The token stays in this browser tab (sessionStorage) and is sent as a bearer token, so
// there is no cookie to forge. UI-side checks are advisory: every rule is enforced by the platform and the engine.

import type { ActivationResult, ApiErrorBody, CheckResult, Draft, Me, ModelDocument, MoveResult, OntologySummary,
  Proposal, Published, Release, ReleaseState, Restored, Stage, Template, UseCase, ValidationResult } from "./types";

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

export const api = {
  me: () => request<Me>("GET", "/platform/v1/me"),
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
  saveDraft: (path: string, document: ModelDocument, expected_revision: number, note: string) =>
    request<Draft>("POST", `${path}/api/v1/model/draft`, { document, expected_revision, note }),
  validate: (path: string, document: ModelDocument) =>
    request<ValidationResult>("POST", `${path}/api/v1/model/validate`, { document }),
  // releases (REL-1a, STU-6): the platform decides who may propose, approve and activate
  releases: (w: string, uc: string) => request<ReleaseState>("GET", `${ws(w)}/${encodeURIComponent(uc)}/releases`),
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
};
