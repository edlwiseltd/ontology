// Pure helpers of the onboarding screen (no I/O). They only arrange what the engine returned for display: which
// items are proposed and which are confirmed, the workflow a model describes, who may do what. Nothing here
// decides validity, permission or readiness.

import { applyItems } from "./model";
import type { ArchitectStatus, ModelDocument, Proposal, ProposalItem } from "./types";

export const SAMPLE_BRIEF =
  "Employees send service requests. A manager must approve the expensive ones, then a team fulfils them and the requester is told.";

export type Standing = "confirmed" | "proposed";

/** How a proposal's generator must be presented: a test double is never called AI. */
export function generatorLabel(p: Pick<Proposal, "ai" | "generator">): string {
  if (p.generator === "sandbox") return "Sandbox architect · test double · not a language model";
  if (p.generator === "blueprint") return "Approved blueprint · not AI";
  return p.ai ? "AI proposal · untrusted until accepted" : "Proposal · not AI";
}

/** Who answers when a proposal is asked for, said exactly: a test double is never called a model, and a provider
 *  that may not be reached is said to be unreachable, with the reason the engine gives. */
export function providerLabel(s: ArchitectStatus | null): { state: string; text: string; tone: "ok" | "warn" | "muted" } {
  if (!s) return { state: "unknown", text: "Checking which architect answers…", tone: "muted" };
  if (s.state === "sandbox") return { state: "sandbox", tone: "muted",
    text: "Sandbox architect: a deterministic test double built on approved templates, not a language model; nothing leaves this platform." };
  if (s.state === "authorised") return { state: "authorised", tone: "ok",
    text: `Authorised provider: ${s.provider} (${s.model}). Your description is sent to it${s.bounded ? ", within the workspace's budget" : ""}; its answer is untrusted until you accept it.` };
  if (s.state === "not_authorised") return { state: "not_authorised", tone: "warn",
    text: `Provider unavailable: ${s.wanted ?? "a provider"} is named for this use case but may not be reached. ${s.reason ?? ""}` };
  return { state: "none", text: "No architect provider for this use case: proposals are unavailable here.", tone: "muted" };
}

/** What a refusal of the AI gateway means for the person, by its kind. */
export function refusalText(kind: unknown, message: string): string {
  if (kind === "budget_exceeded") return `Budget exceeded: nothing was sent. ${message}`;
  if (kind === "not_allowed") return `Data transmission not authorised by the workspace's AI policy: nothing was sent. ${message}`;
  if (kind === "not_configured") return `Provider unavailable: ${message}`;
  return message;
}

/** Where an element comes from, as the engine could establish it. */
export function basisLabel(i: Pick<ProposalItem, "basis">): string {
  return i.basis === "supplied" ? "from your description (cited)" : "inferred · needs your confirmation";
}

export function itemLabel(i: ProposalItem): string {
  if (i.kind === "relationship") return `${i.value.from} —${i.value.type}→ ${i.value.to}`;
  return i.name ?? i.value?.id ?? i.kind;
}

/** The document a person would get by accepting ``items`` on top of the confirmed draft. */
export function preview(confirmed: ModelDocument, items: ProposalItem[]): ModelDocument {
  return applyItems(confirmed, items);
}

/** Whether each entity of a previewed model is already in the confirmed draft or only proposed. */
export function standing(confirmed: ModelDocument, previewed: ModelDocument): Record<string, Standing> {
  const have = new Set(Object.keys(confirmed.entities ?? {}));
  return Object.fromEntries(Object.keys(previewed.entities ?? {}).map((n) => [n, have.has(n) ? "confirmed" : "proposed"]));
}

export interface Transition { entity: string; action: string; from: string; to: string; decidedBy: string; conditions: string[] }

const STATUS = /^\s*([A-Za-z_]\w*)\.status\s*==\s*'([^']+)'\s*$/;

/** The workflow a model describes: each action that moves an entity from one state to another, with who decides
 *  (the reviewer of a human-review rule on it, or the agent) and its other preconditions. */
export function workflow(doc: ModelDocument): Transition[] {
  const reviewers: Record<string, string[]> = {};
  for (const r of doc.rules ?? []) {
    if (r?.type === "human_review" && r.action) {
      (reviewers[r.action] ??= []).push(r.when ? `${r.reviewer} when ${r.when}` : String(r.reviewer));
    }
  }
  const out: Transition[] = [];
  for (const [name, a] of Object.entries<any>(doc.actions ?? {})) {
    const requires: string[] = a?.requires ?? [];
    for (const [entity, changes] of Object.entries<any>(a?.effects ?? {})) {
      const to = changes?.status;
      const from = requires.map((r) => STATUS.exec(r)).find((m) => m && m[1] === entity)?.[2];
      if (!to && !from) continue;
      out.push({ entity, action: name, from: from ?? "any", to: to ?? from ?? "unchanged",
                 decidedBy: reviewers[name]?.length ? `a person: ${reviewers[name].join("; ")}` : "the agent, within the rules",
                 conditions: requires.filter((r) => !(STATUS.exec(r)?.[1] === entity)) });
    }
  }
  const states = (e: string): string[] => doc.entities?.[e]?.states ?? [];
  return out.sort((x, y) => x.entity.localeCompare(y.entity) || states(x.entity).indexOf(x.from) - states(y.entity).indexOf(y.from));
}

export interface AccessLine { rule: string; text: string }

/** Who may do what, as the model's own rules say it (reviews, action, read and write access, mandatory steps). */
export function accessLines(doc: ModelDocument): AccessLine[] {
  const lines: AccessLine[] = [];
  for (const r of doc.rules ?? []) {
    const roles = (r?.roles ?? []).join(", ");
    const when = r?.when ? ` when ${r.when}` : "";
    if (r?.type === "human_review") lines.push({ rule: r.id, text: `${r.action} needs a decision by ${r.reviewer}${when}` });
    else if (r?.type === "action_access") lines.push({ rule: r.id, text: `only ${roles} may ${r.action}${when}` });
    else if (r?.type === "write_access") lines.push({ rule: r.id, text: `only ${roles} may change ${r.field}${when}` });
    else if (r?.type === "data_access") lines.push({ rule: r.id, text: `only ${roles} may read ${r.field}${when}` });
    else if (r?.type === "row_access") lines.push({ rule: r.id, text: `only ${roles} may see ${r.entity} records${when}` });
    else if (r?.type === "mandatory_step") lines.push({ rule: r.id, text: `${r.step} must happen before ${r.before}` });
    else if (r?.type === "prohibition") lines.push({ rule: r.id, text: `${r.action} is prohibited${when}` });
  }
  return lines;
}

/** Counts of provisional items per kind, for the summary line. */
export function countByKind(items: ProposalItem[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const i of items) out[i.kind] = (out[i.kind] ?? 0) + 1;
  return out;
}

/** Provenance kept in the draft for accepted items ("x-" keys are ignored by the engine's strict schema). */
export function withProvenance(doc: ModelDocument, proposal: Pick<Proposal, "id" | "revision" | "generator" | "ai">,
                               items: ProposalItem[]): ModelDocument {
  const d: ModelDocument = JSON.parse(JSON.stringify(doc));
  const studio = (d["x-studio"] ??= {});
  const record = (studio.provenance ??= {});
  for (const i of items) {
    record[`${i.kind}:${itemLabel(i)}`] = { proposal: proposal.id, revision: proposal.revision,
                                           generator: proposal.generator, ai: proposal.ai };
  }
  return d;
}
