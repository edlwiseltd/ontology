import { describe, expect, it } from "vitest";
import { accessLines, basisLabel, countByKind, generatorLabel, itemLabel, preview, providerLabel, refusalText, standing,
         withProvenance, workflow } from "../lib/onboarding";
import type { ProposalItem } from "../lib/types";

const item = (kind: ProposalItem["kind"], name: string | null, value: any): ProposalItem => ({
  id: `model:${kind}:${name ?? "rel"}`, kind, name, value, rationale: "because", status: "provisional",
  provenance: { generator: "sandbox", ai: false } });

const ITEMS: ProposalItem[] = [
  item("entity", "Request", { description: "r", states: ["submitted", "under_review", "approved", "closed"], attributes: { amount: "number" } }),
  item("entity", "Team", { description: "t", states: ["available"], attributes: {} }),
  item("relationship", null, { from: "Team", to: "Request", type: "fulfils", cardinality: "1..*" }),
  item("action", "review_request", { requires: ["Request.status == 'submitted'"], effects: { Request: { status: "under_review" } } }),
  item("action", "approve_request", { requires: ["Request.status == 'under_review'", "Team.status == 'available'"],
                                      effects: { Request: { status: "approved" } } }),
  item("rule", null, { id: "R-APPROVAL", type: "human_review", action: "approve_request", reviewer: "manager",
                       when: "Request.amount >= 1000" }),
  item("rule", null, { id: "R-AMOUNT", type: "write_access", field: "Request.amount", roles: ["manager"] }),
  item("rule", null, { id: "R-NOTIFY", type: "mandatory_step", step: "notify", before: "close" }),
  item("goal", "request_closed", { description: "g", target: "Request.status == 'closed'" }),
];
const CONFIRMED = { name: "desk", version: "0.1.0", entities: { Team: { description: "t", states: ["available"], attributes: {} } } };

describe("onboarding helpers", () => {
  it("never presents a test double as AI", () => {
    expect(generatorLabel({ ai: false, generator: "sandbox" })).toMatch(/test double.*not a language model/);
    expect(generatorLabel({ ai: false, generator: "blueprint" })).toMatch(/not AI/);
    expect(generatorLabel({ ai: true, generator: "model" })).toMatch(/AI proposal.*untrusted/);
    expect(generatorLabel({ ai: false, generator: "model" })).not.toMatch(/^AI/);
  });

  it("keeps proposed and confirmed apart, and does not touch the confirmed draft", () => {
    const before = JSON.stringify(CONFIRMED);
    const previewed = preview(CONFIRMED, ITEMS);
    expect(JSON.stringify(CONFIRMED)).toBe(before);
    expect(standing(CONFIRMED, previewed)).toEqual({ Team: "confirmed", Request: "proposed" });
    expect(Object.keys(previewed.goals)).toEqual(["request_closed"]);  // goals are items too
    expect(previewed.rules).toHaveLength(3);
    expect(standing(previewed, previewed).Request).toBe("confirmed");
  });

  it("reads the workflow and who decides from the model itself", () => {
    const flow = workflow(preview(CONFIRMED, ITEMS));
    expect(flow.map((t) => `${t.entity}:${t.from}>${t.to}:${t.action}`)).toEqual([
      "Request:submitted>under_review:review_request", "Request:under_review>approved:approve_request"]);
    expect(flow[0].decidedBy).toBe("the agent, within the rules");
    expect(flow[1].decidedBy).toBe("a person: manager when Request.amount >= 1000");
    expect(flow[1].conditions).toEqual(["Team.status == 'available'"]);
    expect(workflow({})).toEqual([]);
  });

  it("lists who may do what from the rules", () => {
    expect(accessLines(preview(CONFIRMED, ITEMS)).map((l) => `${l.rule}: ${l.text}`)).toEqual([
      "R-APPROVAL: approve_request needs a decision by manager when Request.amount >= 1000",
      "R-AMOUNT: only manager may change Request.amount",
      "R-NOTIFY: notify must happen before close"]);
  });

  it("labels, counts and records provenance", () => {
    expect(itemLabel(ITEMS[2])).toBe("Team —fulfils→ Request");
    expect(itemLabel(ITEMS[5])).toBe("R-APPROVAL");
    expect(countByKind(ITEMS)).toEqual({ entity: 2, relationship: 1, action: 2, rule: 3, goal: 1 });
    const doc = withProvenance(preview(CONFIRMED, ITEMS), { id: "P-1", revision: 2, generator: "sandbox", ai: false }, ITEMS.slice(0, 1));
    expect(doc["x-studio"].provenance).toEqual({ "entity:Request": { proposal: "P-1", revision: 2, generator: "sandbox", ai: false } });
    expect(doc.entities.Request).toBeDefined();
  });

  it("says exactly who answers, and never calls a test double a model", () => {
    const base = { configured: true, generators: ["blueprint", "model"] };
    const sandbox = providerLabel({ ...base, state: "sandbox", language_model: false });
    expect([sandbox.state, sandbox.tone]).toEqual(["sandbox", "muted"]);
    expect(sandbox.text).toMatch(/test double.*Not a language model.*nothing leaves/i);
    const real = providerLabel({ ...base, state: "authorised", provider: "acme-ai", model: "m-1", language_model: true, bounded: true });
    expect(real.text).toMatch(/Authorised provider: acme-ai \(m-1\).*sent to it, within the workspace's budget.*untrusted/);
    const blocked = providerLabel({ configured: false, generators: ["blueprint"], state: "not_authorised", wanted: "acme-ai",
                                    reason: "the owner has not authorised acme-ai" });
    expect([blocked.state, blocked.tone]).toEqual(["not_authorised", "warn"]);
    expect(blocked.text).toMatch(/Provider unavailable.*may not be reached.*owner has not authorised/);
    expect(providerLabel({ configured: false, generators: ["blueprint"], state: "none" }).text).toMatch(/No architect provider/);
    expect(providerLabel(null).state).toBe("unknown");
  });

  it("turns a refusal of the gateway into what happened, and tells facts from inferences", () => {
    expect(refusalText("budget_exceeded", "the budget is 5 USD")).toMatch(/^Budget exceeded: nothing was sent\. the budget/);
    expect(refusalText("not_allowed", "no personal data")).toMatch(/^Data transmission not authorised.*nothing was sent/);
    expect(refusalText("not_configured", "no policy")).toMatch(/^Provider unavailable: no policy/);
    expect(refusalText(undefined, "something else")).toBe("something else");
    expect(basisLabel({ basis: "supplied" })).toMatch(/from your description/);
    expect(basisLabel({ basis: "inferred" })).toMatch(/inferred.*needs your confirmation/);
    expect(basisLabel({})).toMatch(/inferred/);  // nothing said: never presented as a fact
  });
});
