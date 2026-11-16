// Pure helpers of the agent and tool configuration panel (no I/O). They edit a working copy and arrange the
// engine's answers for display. Validity, permissions and what a tool may do are decided by the engine.

import type { AgentPermission, AgentSpec, ModelDocument, Solution, SolutionDraft, ToolAssignment } from "./types";

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

export function emptyAgent(doc: ModelDocument): AgentSpec {
  return { purpose: "", responsibilities: [], roles: [], goals: Object.keys(doc.goals ?? {}).slice(0, 1),
           autonomy: { mode: "policy" }, tools: [] };
}

export function addAgent(s: Solution | null, name: string, doc: ModelDocument): Solution {
  const next: Solution = clone(s ?? { agents: {} });
  next.agents[name] = emptyAgent(doc);
  return next;
}

export function removeAgent(s: Solution, name: string): Solution {
  const next = clone(s);
  delete next.agents[name];
  return next;
}

export function updateAgent(s: Solution, name: string, change: Partial<AgentSpec>): Solution {
  const next = clone(s);
  next.agents[name] = { ...next.agents[name], ...change };
  return next;
}

/** Assign a catalogue tool to an action of an agent, or remove the assignment (tool ""). */
export function setTool(s: Solution, agent: string, action: string, tool: string, params: Partial<ToolAssignment> = {}): Solution {
  const next = clone(s);
  const tools = next.agents[agent].tools.filter((t) => t.action !== action);
  if (tool) tools.push({ action, tool, ...params });
  next.agents[agent].tools = tools;
  return next;
}

export const toolOf = (spec: AgentSpec, action: string): ToolAssignment | undefined =>
  spec.tools.find((t) => t.action === action);

/** The role names a model's rules refer to (access rules and reviewers). */
export function rolesIn(doc: ModelDocument): string[] {
  const out = new Set<string>();
  for (const r of doc.rules ?? []) {
    for (const role of r?.roles ?? []) out.add(String(role));
    if (r?.type === "human_review" && r.reviewer) out.add(String(r.reviewer));
  }
  return [...out].sort();
}

/** A comma-separated field as a clean list. */
export const listOf = (text: string): string[] => text.split(",").map((v) => v.trim()).filter(Boolean);

export const STATE_LABEL: Record<SolutionDraft["state"], string> = {
  none: "No configuration in the draft", invalid: "Draft · not valid", validated: "Draft · validated by the engine" };

export const STATUS_LABEL: Record<AgentPermission["status"], string> = {
  autonomous: "the agent acts on its own", conditional: "depends on the case (see conditions)",
  review_required: "a person decides", refused: "refused by the rules", not_assigned: "not assigned" };

/** Why a status is what it is, in one line (the engine's reasons, joined). */
export function reasonsOf(p: AgentPermission): string {
  const reviews = p.reviews.map((r) => `${r.reviewer}${r.when ? ` when ${r.when}` : ""} (${r.rule})`);
  return [...p.refused, ...p.conditions, ...(reviews.length ? [`review by ${reviews.join("; ")}`] : [])].join(" · ");
}

export interface FlowNode { id: string; label: string; kind: "agent" | "action" | "tool"; status?: string; x: number; y: number }
export interface FlowEdge { id: string; source: string; target: string }

/** Agents, the actions they may perform and the tools that perform them, as a three-column graph. */
export function agentGraph(s: Solution | null, permissions: Record<string, AgentPermission[]>): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const nodes: FlowNode[] = [];
  const edges: FlowEdge[] = [];
  let row = 0;
  for (const [name, spec] of Object.entries(s?.agents ?? {})) {
    const start = row;
    for (const t of spec.tools) {
      const status = permissions[name]?.find((p) => p.action === t.action)?.status;
      nodes.push({ id: `${name}:${t.action}`, label: t.action, kind: "action", status, x: 300, y: row * 64 });
      nodes.push({ id: `${name}:${t.action}:tool`, label: t.tool.replace("simulated.", "simulated · "), kind: "tool", x: 600, y: row * 64 });
      edges.push({ id: `e-${name}-${t.action}`, source: name, target: `${name}:${t.action}` });
      edges.push({ id: `t-${name}-${t.action}`, source: `${name}:${t.action}`, target: `${name}:${t.action}:tool` });
      row += 1;
    }
    nodes.push({ id: name, label: name, kind: "agent", x: 0, y: ((start + Math.max(row, start + 1) - 1) / 2) * 64 });
    if (row === start) row += 1;
  }
  return { nodes, edges };
}
