// The only server-side code in Studio: a narrow relay to the Autology platform, so the browser talks to one origin.
// It decides nothing. It forwards GET and POST under /platform/ and /w/ only, with Authorization, Content-Type and
// the expected configuration only, never follows redirects, bounds request bodies, and answers 502 when the platform cannot be reached.
// Every permission, check, stage and isolation rule is the platform's.

export const FORWARDED_PREFIXES = ["/platform/", "/w/"];
// x-autology-configuration: the configuration a request was written for; the Engine refuses it when another runs
export const FORWARDED_HEADERS = ["authorization", "content-type", "x-autology-configuration"];
export const MAX_BODY = 1_000_000;

export function forwardable(method: string, path: string): boolean {
  return (method === "GET" || method === "POST") && FORWARDED_PREFIXES.some((p) => path.startsWith(p))
    && !path.includes("..") && !path.includes("//") && !path.includes("\\") && !/%2e|%2f|%5c/i.test(path);
}

// For an application runtime served from its own origin: NOT this deployment, and nothing calls it (owner decision
// D35; planning/AUTOLOGY_D35_RUNTIME_SEPARATION_ASSESSMENT.md). A relay of the application plane would forward the
// Engine's versioned API of one use case, and nothing of the platform's administration or of the unversioned API.
export function runtimeForwardable(method: string, path: string): boolean {
  return forwardable(method, path) && /^\/w\/[^/]+\/u\/[^/]+\/api\/v1\/[^/]/.test(path);
}

export function platformBase(raw: string | undefined): string {
  if (!raw) throw new Error("set AUTOLOGY_PLATFORM_URL to the platform's base URL, e.g. http://127.0.0.1:8700");
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol) || (url.pathname !== "/" && url.pathname !== "") || url.search || url.hash) {
    throw new Error("AUTOLOGY_PLATFORM_URL must be a base URL such as http://127.0.0.1:8700");
  }
  return `${url.protocol}//${url.host}`;
}

function json(status: number, error: string): Response {
  return new Response(JSON.stringify({ error }), { status, headers: { "Content-Type": "application/json" } });
}

export async function forward(req: Request, base = process.env.AUTOLOGY_PLATFORM_URL,
                              fetcher: typeof fetch = fetch): Promise<Response> {
  const url = new URL(req.url);
  if (!forwardable(req.method, url.pathname)) return json(404, "not found");
  let target: string;
  try {
    target = platformBase(base) + url.pathname + url.search;
  } catch (e) {
    return json(500, (e as Error).message);
  }
  const headers = new Headers();
  for (const name of FORWARDED_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  let body: ArrayBuffer | undefined;
  if (req.method === "POST") {
    const length = req.headers.get("content-length");
    if (length !== null && !/^\d+$/.test(length)) return json(411, "a valid Content-Length is required");
    body = await req.arrayBuffer();
    if (body.byteLength > MAX_BODY) return json(413, "request body too large");
  }
  try {
    const res = await fetcher(target, { method: req.method, headers, body, redirect: "manual", cache: "no-store" });
    const out = new Headers({ "Content-Type": res.headers.get("content-type") ?? "application/json",
                              "Cache-Control": "no-store" });
    // "retry in N seconds" is the platform's answer to too many requests (429) or an engine being switched (503)
    const retry = res.headers.get("retry-after");
    if (retry && /^\d{1,5}$/.test(retry)) out.set("Retry-After", retry);
    return new Response(await res.arrayBuffer(), { status: res.status, headers: out });
  } catch {
    return json(502, "the platform cannot be reached");
  }
}
