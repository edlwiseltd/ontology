// The typed client Studio uses. Same origin only: requests go to Studio's relay (lib/forward.ts), which forwards
// them to the platform. The token stays in this browser tab (sessionStorage) and is sent as a bearer token, so
// there is no cookie to forge. UI-side checks are advisory: every rule is enforced by the platform and the engine.

import type { CheckResult, Draft, Me, ModelDocument, OntologySummary, Proposal, Question, Stage, Template, UseCase,
  Validation } from "./types";

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
  if (!res.ok) throw new ApiError(res.status, String(data.error ?? `HTTP ${res.status}`), data);
  return data as T;
}

const ws = (id: string) => `/platform/workspaces/${encodeURIComponent(id)}/use-cases`;

export const api = {
  me: () => request<Me>("GET", "/platform/me"),
  useCases: (w: string) => request<{ items: UseCase[] }>("GET", ws(w)),
  useCase: (w: string, uc: string) => request<UseCase>("GET", `${ws(w)}/${encodeURIComponent(uc)}`),
  checks: (w: string, uc: string, to: Stage) =>
    request<CheckResult>("GET", `${ws(w)}/${encodeURIComponent(uc)}/checks?to=${to}`),
  move: (w: string, uc: string, to: Stage, reason: string) =>
    request<CheckResult & { use_case: UseCase }>("POST", `${ws(w)}/${encodeURIComponent(uc)}/stage`, { to, reason }),
  templates: () => request<{ items: Template[] }>("GET", "/platform/templates"),
  createUseCase: (w: string, id: string, name: string, template: string) =>
    request<UseCase>("POST", ws(w), { id, name, template }),
  ontology: (path: string) => request<OntologySummary>("GET", `${path}/api/ontology`),
  // model design: drafts never change what runs; the engine validates and decides
  draft: (path: string) => request<Draft>("GET", `${path}/api/model/draft`),
  saveDraft: (path: string, document: ModelDocument, expected_revision: number, note: string) =>
    request<Draft>("POST", `${path}/api/model/draft`, { document, expected_revision, note }),
  validate: (path: string, document: ModelDocument) =>
    request<{ validation: Validation; questions: Question[] }>("POST", `${path}/api/model/validate`, { document }),
  propose: (path: string, brief: string, document: ModelDocument) =>
    request<Proposal>("POST", `${path}/api/architect/proposals`, { brief, document }),
};
