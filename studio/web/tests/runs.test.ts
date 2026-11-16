import { describe, expect, it } from "vitest";
import { cancellable, mayDecide, releaseOf, resumable, statusClass, stepLine, trace, STATUS_TEXT } from "../lib/runs";
import type { ReviewView } from "../lib/runs";

const review: ReviewView = { review_id: "r1", run_id: "run1", action: "approve", reviewers: ["manager"], status: "pending",
                             created_at: "2026-11-16T00:00:00Z", request: {} };

describe("run helpers", () => {
  it("offers cancel and resume only where the engine would accept them", () => {
    expect(["awaiting_review", "deferred", "paused"].every(cancellable)).toBe(true);
    expect(["completed", "cancelled", "escalated", "blocked", "uncertain"].some(cancellable)).toBe(false);
    expect([resumable("deferred"), resumable("paused"), resumable("awaiting_review")]).toEqual([true, true, false]);
    expect([statusClass("completed"), statusClass("deferred"), statusClass("cancelled")]).toEqual(["okpill", "warnpill", ""]);
    expect(STATUS_TEXT.cancelled).toBe("cancelled");
  });

  it("says which tool acted and that it was simulated", () => {
    expect(stepLine({ index: 0, action: "fulfil", verdict: "allow", outcome: "done", executed_by: "agent", tool: "agent.fulfil",
                      reviewer: "maria", environment: "simulated" })).toBe("allow → done · agent.fulfil (simulated) · decided by maria");
    expect(stepLine({ index: 1, action: "x", verdict: "deny", outcome: null, executed_by: null, reviewer: null, tool: null,
                      environment: null })).toBe("deny · no tool");
  });

  it("links a run to the release whose configuration it ran on", () => {
    const releases = [{ number: 1, fingerprint: "aaa" }, { number: 2, fingerprint: "bbb" }];
    expect(releaseOf({ configuration: "bbb" }, releases)).toBe(2);
    expect(releaseOf({ configuration: "zzz" }, releases)).toBeNull();
    expect(releaseOf({}, releases)).toBeNull();
  });

  it("offers a decision only to a person who holds the reviewer role and did not start the run", () => {
    const maria = { name: "maria", permissions: ["read", "review"], reviewer_roles: ["manager"], kind: "person" };
    expect(mayDecide(maria, review, { started_by: "hana" })).toBe(true);
    expect(mayDecide(maria, review, { started_by: "maria" })).toBe(false);  // never one's own run
    expect(mayDecide({ ...maria, reviewer_roles: ["auditor"] }, review, { started_by: "hana" })).toBe(false);
    expect(mayDecide({ ...maria, permissions: ["read"] }, review, { started_by: "hana" })).toBe(false);
    expect(mayDecide({ ...maria, kind: "service" }, review, { started_by: "hana" })).toBe(false);  // a machine never approves
    expect(mayDecide(null, review, { started_by: "hana" })).toBe(false);
  });

  it("turns the audit chain into a readable decision trace, in order, leaving the plumbing in the chain", () => {
    const rows = trace([
      { seq: 0, timestamp: "t0", event: "run.start", data: { acting_as: "hana", agent: "a", goal: "g", ontology: "m@1" }, hash: "h0" },
      { seq: 1, timestamp: "t1", event: "plan", data: { plan: ["assess", "expedite"] }, hash: "h1" },
      { seq: 2, timestamp: "t2", event: "decision", data: { action: "expedite", verdict: "review", rules: ["R1"] }, hash: "h2" },
      { seq: 3, timestamp: "t3", event: "step.intent", data: { key: "abc" }, hash: "h3" },
      { seq: 4, timestamp: "t4", event: "review.requested", data: { action: "expedite", roles: ["manager"], reasons: ["costly"] }, hash: "h4" },
      { seq: 5, timestamp: "t5", event: "review.decision", data: { action: "expedite", approved: false, reviewer: "maria", comment: "no" }, hash: "h5" },
      { seq: 6, timestamp: "t6", event: "tool.error", data: { action: "compare", tool: "a.compare", attempt: 2, error: "down" }, hash: "h6" },
      { seq: 7, timestamp: "t7", event: "step", data: { action: "assess", tool: "a.assess", outcome: "done", message: "ok (simulated)" }, hash: "h7" },
      { seq: 8, timestamp: "t8", event: "run.cancelled", data: { by: "hana", reason: "duplicate" }, hash: "h8" },
      { seq: 9, timestamp: "t9", event: "run.end", data: { status: "cancelled", escalation: { reason: "cancelled by hana: duplicate" } }, hash: "h9" },
    ]);
    expect(rows.map((r) => r.seq)).toEqual([0, 1, 2, 4, 5, 6, 7, 8, 9]);
    expect(rows.map((r) => r.label)).toEqual(["run started", "plan", "policy check", "review requested", "review decided", "tool failed",
                                              "action executed", "run cancelled", "run stopped"]);
    expect(rows[1].detail).toBe("assess → expedite");
    expect(rows[2].detail).toBe("expedite: review (rules R1)");
    expect(rows[4].detail).toBe("expedite: refused by maria — no");
    expect(rows[5].detail).toBe("compare via a.compare, attempt 2: down");
    expect(rows[6].detail).toBe("assess via a.assess → done: ok (simulated)");
    expect(rows[8].detail).toBe("status cancelled — cancelled by hana: duplicate");
  });
});
