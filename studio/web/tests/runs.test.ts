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
    expect(stepLine({ index: 0, action: "fulfil", verdict: "allow", outcome: "done", executed_by: "agent.fulfil",
                      reviewer: "maria", environment: "simulated" })).toBe("allow → done · agent.fulfil (simulated) · decided by maria");
    expect(stepLine({ index: 1, action: "x", verdict: "deny", outcome: null, executed_by: null, reviewer: null })).toBe("deny · no tool");
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

  it("turns the audit chain into a readable decision trace, in order", () => {
    const rows = trace([
      { seq: 0, timestamp: "t0", event: "run.start", data: { goal: "closed" }, hash: "h0" },
      { seq: 1, timestamp: "t1", event: "governance.decision", data: { action: "approve", verdict: "review", reasons: ["R1"] }, hash: "h1" },
      { seq: 2, timestamp: "t2", event: "review.decision", data: { action: "approve", approved: false, reviewer: "maria" }, hash: "h2" },
      { seq: 3, timestamp: "t3", event: "run.cancelled", data: { by: "hana", reason: "duplicate" }, hash: "h3" },
      { seq: 4, timestamp: "t4", event: "run.end", data: { status: "cancelled" }, hash: "h4" },
    ]);
    expect(rows.map((r) => r.seq)).toEqual([0, 1, 2, 3, 4]);
    expect(rows[1].detail).toBe('approve: review (["R1"])');
    expect(rows[2].detail).toBe("approve: declined by maria");
    expect(rows[3].detail).toBe("by hana: duplicate");
    expect(rows[4].detail).toBe("status cancelled");
  });
});
