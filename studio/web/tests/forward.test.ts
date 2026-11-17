import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { forward, forwardable, platformBase, runtimeForwardable } from "../lib/forward";

describe("the relay to the platform", () => {
  it("forwards only GET and POST under /platform/ and /w/", () => {
    expect(forwardable("GET", "/platform/me")).toBe(true);
    expect(forwardable("POST", "/w/acme/u/claims/api/runs")).toBe(true);
    for (const [m, p] of [["GET", "/api/health"], ["PUT", "/platform/me"], ["DELETE", "/w/a/u/b/api/x"],
                          ["GET", "/platform/../api"], ["GET", "/w//u"], ["GET", "/w/a%2f..%2fb"], ["GET", "/w/a\\b"]]) {
      expect(forwardable(m, p)).toBe(false);
    }
  });

  it("has a narrower rule ready for a runtime served on its own: one use case's versioned API, no administration (not in use)", () => {
    expect(runtimeForwardable("GET", "/w/acme/u/claims/api/v1/application")).toBe(true);
    expect(runtimeForwardable("POST", "/w/acme/u/claims/api/v1/runs")).toBe(true);
    for (const [m, p] of [["GET", "/platform/v1/workspaces/acme/members"], ["POST", "/platform/v1/workspaces/acme/grants"],
                          ["GET", "/platform/openapi.json"], ["GET", "/w/acme/u/claims/api/runs"], ["GET", "/w/acme/api/v1/x"],
                          ["GET", "/w/acme/u/claims/api/v1/"], ["GET", "/w/acme/u/claims/api/v1/../../../../platform/v1/me"],
                          ["PUT", "/w/acme/u/claims/api/v1/objects"], ["GET", "/w/acme/u/claims/console"]]) {
      expect(runtimeForwardable(m, p), p).toBe(false);
    }
    const route = (dir: string) => readFileSync(join(__dirname, "..", "app", dir, "[...path]", "route.ts"), "utf8");
    for (const dir of ["platform", "w"]) expect(route(dir)).not.toContain("runtimeForwardable");  // prepared, not wired
  });

  it("accepts only a base URL for the platform", () => {
    expect(platformBase("http://127.0.0.1:8700/")).toBe("http://127.0.0.1:8700");
    for (const bad of [undefined, "ftp://x", "http://h/w/acme", "http://h?x=1", "file:///etc/passwd"]) {
      expect(() => platformBase(bad)).toThrow();
    }
  });

  it("passes on Authorization and Content-Type only, never redirects, and refuses other paths", async () => {
    const seen: { url: string; init: RequestInit }[] = [];
    const fake = (async (url: string, init: RequestInit) => {
      seen.push({ url, init });
      return new Response('{"ok":true}', { status: 200, headers: { "Content-Type": "application/json", "Set-Cookie": "x=1" } });
    }) as unknown as typeof fetch;
    const req = new Request("http://studio.local/platform/me?x=1", {
      headers: { Authorization: "Bearer t", Cookie: "session=1", "X-Forwarded-For": "1.2.3.4", "X-Custom": "z" } });
    const res = await forward(req, "http://127.0.0.1:8700", fake);
    expect(res.status).toBe(200);
    expect(res.headers.get("set-cookie")).toBeNull();  // nothing from the platform but the type comes back
    expect(seen[0].url).toBe("http://127.0.0.1:8700/platform/me?x=1");
    expect(seen[0].init.redirect).toBe("manual");
    const h = seen[0].init.headers as Headers;
    expect([...h.keys()].sort()).toEqual(["authorization"]);
    const refused = await forward(new Request("http://studio.local/api/health"), "http://127.0.0.1:8700", fake);
    expect(refused.status).toBe(404);
    expect(seen.length).toBe(1);
  });

  it("bounds bodies and reports an unreachable platform", async () => {
    const big = new Request("http://studio.local/platform/x", { method: "POST", body: "x".repeat(1_000_001) });
    expect((await forward(big, "http://127.0.0.1:8700", fetch)).status).toBe(413);
    const down = (async () => { throw new Error("refused"); }) as unknown as typeof fetch;
    const res = await forward(new Request("http://studio.local/platform/me"), "http://127.0.0.1:9", down);
    expect(res.status).toBe(502);
  });
});
