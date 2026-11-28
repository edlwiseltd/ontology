import { describe, expect, it } from "vitest";
import { addAgent, agentGraph, listOf, reasonsOf, removeAgent, rolesIn, setTool, STATE_LABEL, STATUS_LABEL, toolOf,
         updateAgent } from "../lib/solution";
import type { AgentPermission, Solution } from "../lib/types";

const DOC = { name: "desk", goals: { closed: {}, told: {} }, actions: { approve: {}, fulfil: {} },
              rules: [{ id: "R1", type: "human_review", action: "approve", reviewer: "manager" },
                      { id: "R2", type: "action_access", action: "fulfil", roles: ["clerk", "manager"] }] };
const perm = (action: string, status: AgentPermission["status"], extra: Partial<AgentPermission> = {}): AgentPermission => ({
  action, status, tool: null, simulated: false, side_effect: "none", refused: [], conditions: [], reviews: [], ...extra });

describe("agent and tool configuration helpers", () => {
  it("edits a working copy without touching the one it was given", () => {
    const first = addAgent(null, "desk_agent", DOC);
    expect(first.agents.desk_agent).toEqual({ purpose: "", responsibilities: [], roles: [], goals: ["closed"],
                                              autonomy: { mode: "policy" }, tools: [] });
    const second = updateAgent(first, "desk_agent", { roles: ["clerk"] });
    expect(first.agents.desk_agent.roles).toEqual([]);
    expect(second.agents.desk_agent.roles).toEqual(["clerk"]);
    expect(removeAgent(second, "desk_agent").agents).toEqual({});
    expect(second.agents.desk_agent).toBeDefined();
  });

  it("permits an action by assigning one tool to it, and withdraws the permission by removing it", () => {
    let s: Solution = addAgent(null, "a", DOC);
    s = setTool(s, "a", "approve", "simulated.succeed");
    s = setTool(s, "a", "fulfil", "simulated.fail", { error: "system down" });
    s = setTool(s, "a", "approve", "simulated.decision_table", { rows: [{ outcome: "approved" }] });
    expect(s.agents.a.tools).toHaveLength(2);  // one tool per action, never two
    expect(toolOf(s.agents.a, "approve")).toEqual({ action: "approve", tool: "simulated.decision_table", rows: [{ outcome: "approved" }] });
    expect(toolOf(s.agents.a, "fulfil")?.error).toBe("system down");
    s = setTool(s, "a", "fulfil", "");
    expect(toolOf(s.agents.a, "fulfil")).toBeUndefined();
  });

  it("offers the roles the model's rules name, and nothing else", () => {
    expect(rolesIn(DOC)).toEqual(["clerk", "manager"]);
    expect(rolesIn({})).toEqual([]);
    expect(listOf(" clerk, ,manager ,")).toEqual(["clerk", "manager"]);
  });

  it("shows the engine's reasons as they are, and labels every state it can answer", () => {
    expect(reasonsOf(perm("fulfil", "refused", { refused: ["R2: only clerk may perform it"] }))).toBe("R2: only clerk may perform it");
    expect(reasonsOf(perm("approve", "conditional", { conditions: ["R9: prohibited when X.a > 1"],
                                                      reviews: [{ reviewer: "manager", when: "X.a > 5", rule: "R1" }] })))
      .toBe("R9: prohibited when X.a > 1 · review by manager when X.a > 5 (R1)");
    expect(reasonsOf(perm("approve", "autonomous"))).toBe("");
    expect(Object.keys(STATUS_LABEL).sort()).toEqual(["autonomous", "conditional", "not_assigned", "refused", "review_required"]);
    expect(Object.keys(STATE_LABEL).sort()).toEqual(["invalid", "none", "validated"]);
  });

  it("draws agents, their permitted actions and the simulated tools behind them", () => {
    let s: Solution = addAgent(null, "a", DOC);
    s = setTool(s, "a", "approve", "simulated.succeed");
    s = setTool(s, "a", "fulfil", "simulated.fail");
    s = addAgent(s, "idle", DOC);
    const g = agentGraph(s, { a: [perm("approve", "review_required"), perm("fulfil", "refused")] });
    expect(g.nodes.filter((n) => n.kind === "agent").map((n) => n.id)).toEqual(["a", "idle"]);
    expect(g.nodes.filter((n) => n.kind === "action").map((n) => [n.label, n.status])).toEqual([["approve", "review_required"], ["fulfil", "refused"]]);
    expect(g.nodes.filter((n) => n.kind === "tool").map((n) => n.label)).toEqual(["simulated · succeed", "simulated · fail"]);
    expect(g.edges).toHaveLength(4);
    expect(new Set(g.nodes.map((n) => n.id)).size).toBe(g.nodes.length);
    expect(agentGraph(null, {})).toEqual({ nodes: [], edges: [] });
  });
});
