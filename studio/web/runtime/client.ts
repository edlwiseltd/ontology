// The application runtime's own connection to the Engine. Same origin only (the relay forwards to the platform).
// It has a token of its own, kept for this tab; it never reads Studio's. Every request can name the configuration
// the application was read for: the Engine refuses it when another one runs (see autology/applications.py).

const TOKEN_KEY = "autology-app-token";
let memoryToken: string | null = null;

export function getToken(): string | null {
  try { return sessionStorage.getItem(TOKEN_KEY) ?? memoryToken; } catch { return memoryToken; }
}
export function setToken(token: string | null): void {
  memoryToken = token;
  try { if (token) sessionStorage.setItem(TOKEN_KEY, token); else sessionStorage.removeItem(TOKEN_KEY); } catch { /* memory only */ }
}

export class EngineError extends Error {
  constructor(public status: number, message: string, public details: Record<string, unknown> = {}) { super(message); }
}

export const enginePath = (workspace: string, useCase: string): string =>
  `/w/${encodeURIComponent(workspace)}/u/${encodeURIComponent(useCase)}/api/v1`;

/** ``heard`` is called when the Engine answered successfully: a screen may show when it last did. */
export interface Caller { base: string; token: () => string | null; configuration?: string; heard?: () => void }

export async function call<T>(who: Caller, method: "GET" | "POST", path: string, body?: unknown,
                              fetcher: typeof fetch = fetch): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${who.token() ?? ""}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (who.configuration) headers["X-Autology-Configuration"] = who.configuration;
  const res = await fetcher(who.base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body),
                                               redirect: "error", cache: "no-store" });
  let data: Record<string, unknown> = {};
  try { data = await res.json(); } catch { data = {}; }
  if (!res.ok) {
    const e = data.error as { message?: string; details?: Record<string, unknown> } | string | undefined;
    const message = typeof e === "string" ? e : e?.message ?? `HTTP ${res.status}`;
    throw new EngineError(res.status, message, typeof e === "object" && e?.details ? e.details : {});
  }
  who.heard?.();
  return data as T;
}
