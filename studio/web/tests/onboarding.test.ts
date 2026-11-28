import { describe, expect, it } from "vitest";
import { accessLines, basisLabel, countByKind, generatorLabel, itemLabel, preview, providerLabel, refusalText, releaseAi, standing,
         withProvenance, workflow, ledgerLine } from "../lib/onboarding";
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
    // an element from a template carries no origin: the draft says "unknown", it does not make one up
    expect(doc["x-studio"].provenance).toEqual({ "entity:Request": { proposal: "P-1", revision: 2, generator: "sandbox", ai: false,
      basis: "inferred", origin: "unknown", evidence: [] } });
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

  it("names the model a release may ask, and whether it is served now, without any key", () => {
    expect(releaseAi(null)).toContain("asks no architect");
    expect(releaseAi({ provider: "sandbox" })).toContain("not a language model");
    const named = { provider: "anthropic", model: "claude-opus-5-5", policy_terms: "0123456789abcdef", content: "synthetic" };
    expect(releaseAi(named)).toBe("anthropic · claude-opus-5-5 · policy terms 0123456789abcdef · synthetic data only");
    expect(releaseAi(named, { served: true, reason: "" })).toContain("served by the workspace's policy now");
    expect(releaseAi(named, { served: false, reason: "the workspace's policy names another model" }))
      .toContain("not served now: the workspace's policy names another model");
    const label = providerLabel({ configured: true, generators: ["model"], state: "authorised", provider: "anthropic",
      model: "claude-opus-5-5", bounded: true, content: "synthetic" } as any);
    expect(label.text).toContain("declared synthetic");
    expect(label.text).toContain("claude-opus-5-5");
  });
});

describe("the spending ledger line", () => {
  const base = { available: true, problem: "", id: "adopted-0123456789abcdef0123", entries: 27, outside_deployment: true,
    bound_to_authorisation: true, history: [{ period: "2026-11", spent_usd: 4.418875, reserved_usd: 0 }] };
  it("says where the ledger stands and what was spent, period by period", () => {
    const line = ledgerLine({ ledger: base });
    expect(line).toContain("27 entries");
    expect(line).toContain("kept outside this deployment, named by the owner's authorisation");
    expect(line).toContain("2026-11: 4.418875 spent");
    expect(ledgerLine({ ledger: { ...base, history: [{ period: "2026-11", spent_usd: 1, reserved_usd: 0.3, carried_forward_usd: 1 }] } }))
      .toContain("2026-11: 1 spent, 0.3 held (1 carried forward)");
  });
  it("never shows a figure for a ledger that cannot be read, and says nothing is sent", () => {
    const line = ledgerLine({ ledger: { ...base, available: false, problem: "there is no spending ledger at /durable/ledger.db", history: [] } });
    expect(line).toContain("unavailable: there is no spending ledger");
    expect(line).toContain("Nothing is sent without it");
    expect(line).not.toContain("spent");
    expect(ledgerLine({ ledger: { ...base, outside_deployment: false, bound_to_authorisation: false } })).toContain("a real provider needs one kept outside");
    expect(ledgerLine({})).toBe("—");
  });
});
