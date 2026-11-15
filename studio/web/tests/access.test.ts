import { describe, expect, it } from "vitest";
import { accessLabel, approvalHint, roleOf, splitList, tokenLabel } from "../lib/access";
import { forward } from "../lib/forward";

describe("words for what the platform reports about access", () => {
  it("names roles without implying data access", () => {
    expect(roleOf({ workspace_admin: true, tenant_admin: false, approver: false, kind: "person" })).toBe("workspace administrator");
    expect(roleOf({ workspace_admin: true, tenant_admin: true, approver: false, kind: "person" })).toBe("tenant administrator");
    expect(roleOf({ workspace_admin: false, tenant_admin: false, approver: true, kind: "person" })).toBe("approver");
    expect(roleOf({ workspace_admin: false, tenant_admin: false, approver: false, kind: "service" })).toBe("member (service identity)");
  });

  it("says plainly what an identity may do in a use case", () => {
    expect(accessLabel(undefined)).toBe("no access");
    expect(accessLabel({ permissions: [], data_access: "none" })).toBe("no access");
    expect(accessLabel({ permissions: ["configure"], data_access: "none" })).toBe("configure — administration only, no business data");
    expect(accessLabel({ permissions: ["read", "run"], data_access: "scoped" })).toBe("read, run — data within row and field rules");
    expect(accessLabel({ permissions: ["admin"], data_access: "unrestricted" })).toBe("admin — unrestricted data access");
  });

  it("describes a token's state", () => {
    expect(tokenLabel({ token: "active", token_expires_at: "2027-02-13T10:00:00+00:00" })).toBe("valid until 2027-02-13");
    expect(tokenLabel({ token: "expired", token_expires_at: "2026-01-01T00:00:00+00:00" })).toBe("expired 2026-01-01");
    expect(tokenLabel({ token: "revoked", token_expires_at: null })).toBe("revoked");
    expect(tokenLabel({ token: "none", token_expires_at: null })).toBe("no token (revoked)");
  });

  it("only hints at who can approve: the proposer and the grantee are told why not", () => {
    const you = { member: "ada", may_administer: true, may_approve: true };
    expect(approvalHint(you, "ada@acme", { proposed_by: "ada@acme", member: "zoe" }).offer).toBe(false);
    expect(approvalHint(you, "ada@acme", { proposed_by: "maria@acme", member: "ada" }).why).toContain("for you");
    expect(approvalHint(you, "ada@acme", { proposed_by: "maria@acme", member: "zoe" })).toEqual({ offer: true, why: "" });
    expect(approvalHint({ member: "hana", may_administer: false, may_approve: false }, "hana@acme",
                        { proposed_by: "ada@acme", member: "zoe" }).offer).toBe(false);
    expect(approvalHint(undefined, "x@acme", { proposed_by: "ada@acme", member: "zoe" }).offer).toBe(false);
  });

  it("splits a comma-separated list of roles", () => {
    expect(splitList(" claims_handler , finance,, ")).toEqual(["claims_handler", "finance"]);
    expect(splitList("")).toEqual([]);
  });
});

describe("the relay passes on the platform's retry advice", () => {
  it("keeps Retry-After on 429 and 503, and nothing else", async () => {
    const fake = (async () => new Response('{"error":"too many requests"}', {
      status: 429, headers: { "Content-Type": "application/json", "Retry-After": "17", "X-Other": "1" } })) as unknown as typeof fetch;
    const res = await forward(new Request("http://studio.local/platform/v1/me"), "http://127.0.0.1:8700", fake);
    expect(res.status).toBe(429);
    expect(res.headers.get("retry-after")).toBe("17");
    expect(res.headers.get("x-other")).toBeNull();
    const odd = (async () => new Response("{}", { status: 503, headers: { "Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT" } })) as unknown as typeof fetch;
    const res2 = await forward(new Request("http://studio.local/platform/v1/me"), "http://127.0.0.1:8700", odd);
    expect(res2.headers.get("retry-after")).toBeNull();  // only a number of seconds is passed on
  });
});
