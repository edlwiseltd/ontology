// Stored architect proposals as design sessions: what is listed, how two revisions differ, and why an element was
// proposed. Pure functions over what the engine returns; Studio stores nothing of its own and decides nothing.

import { itemLabel } from "./onboarding";
import type { Proposal, ProposalItem, ProposalList } from "./types";

type Listed = ProposalList["items"][number];
type Revision = NonNullable<Proposal["history"]>[number];
type Design = { draft_revision?: number | null; proposal?: { proposal: string; revision: number } | null } | null | undefined;
type ReleaseRef = { number: number; status: string; design?: Design };

/** Who generated a revision, in words that never call a test double a model. */
export function generatedBy(r: { generator?: string | null; ai?: boolean; provider?: string | null; model?: string | null }): string {
  if (r.generator === "blueprint") return "approved template (no language model)";
  if (!r.ai) return `test double (${r.provider ?? "sandbox"}; not a language model)`;
  return `${r.provider ?? "provider not recorded"} · ${r.model ?? "model not recorded"}`;
}

/** One stored session, as a line of the list. */
export function sessionLine(p: Listed): string {
  const parts = [`${p.revisions} revision${p.revisions === 1 ? "" : "s"}`, `${p.items ?? 0} element(s)`,
                 (p.open_questions ?? 0) > 0 ? `${p.open_questions} open question(s)` : "no open question",
                 generatedBy(p)];
  if (typeof p.spent_usd === "number" && p.spent_usd > 0) parts.push(`${p.spent_usd} USD already spent`);
  if ((p.drafts?.length ?? 0) > 0) parts.push(`saved as draft revision ${p.drafts!.join(", ")}`);
  return parts.join(" · ");
}

/** One revision of a session, as a line of its history. */
export function revisionLine(r: Revision): string {
  const asked = r.feedback ? ` · asked: “${r.feedback.length > 80 ? r.feedback.slice(0, 77) + "…" : r.feedback}”` : "";
  const cost = typeof r.cost_usd === "number" && r.cost_usd > 0 ? ` · ${r.cost_usd} USD` : "";
  return `revision ${r.revision} · ${r.at.slice(0, 16).replace("T", " ")} · ${r.created_by} · ${generatedBy(r)} · ${r.items} element(s), `
    + `${r.rejected} refused, ${r.open_questions} open question(s) · ${r.answers.length} answer(s)${cost}${asked}`;
}

export interface RevisionDiff {
  added: string[]; removed: string[]; changed: { label: string; what: string[] }[]; unchanged: number;
  answers: string[]; questionsClosed: string[]; questionsOpened: string[]; sameModel: boolean;
}

function keyed(items: ProposalItem[]): Map<string, ProposalItem> {
  return new Map(items.map((i) => [`${i.kind} ${itemLabel(i)}`, i]));
}

/** What differs between two revisions of one proposal (``from`` the earlier one). Elements are matched by kind and
 *  name; a changed element says what changed: its definition, where it comes from, its basis or its confidence. */
export function compareRevisions(from: Proposal, to: Proposal): RevisionDiff {
  const a = keyed(from.items), b = keyed(to.items);
  const added = [...b.keys()].filter((k) => !a.has(k)).sort();
  const removed = [...a.keys()].filter((k) => !b.has(k)).sort();
  const changed: RevisionDiff["changed"] = [];
  let unchanged = 0;
  for (const [label, before] of a) {
    const after = b.get(label);
    if (!after) continue;
    const what: string[] = [];
    if (JSON.stringify(before.value) !== JSON.stringify(after.value)) what.push("definition");
    if ((before.origin ?? "") !== (after.origin ?? "")) what.push(`origin: ${originLabel(before)} → ${originLabel(after)}`);
    if ((before.basis ?? "") !== (after.basis ?? "")) what.push(`basis: ${before.basis ?? "?"} → ${after.basis ?? "?"}`);
    if (before.confidence !== after.confidence) what.push(`confidence: ${before.confidence ?? "?"} → ${after.confidence ?? "?"}`);
    if (what.length) changed.push({ label, what }); else unchanged += 1;
  }
  const had = new Map((from.answers ?? []).map((x) => [x.id, x.answer]));
  const answers = (to.answers ?? []).filter((x) => had.get(x.id) !== x.answer).map((x) => `${x.id}: ${x.answer}`);
  const asked = new Set((from.questions ?? []).map((q) => q.id)), asks = new Set((to.questions ?? []).map((q) => q.id));
  return { added, removed, changed: changed.sort((x, y) => x.label.localeCompare(y.label)), unchanged, answers,
           questionsClosed: [...asked].filter((q) => !asks.has(q)), questionsOpened: [...asks].filter((q) => !asked.has(q)),
           sameModel: (from.provider ?? "") === (to.provider ?? "") && (from.model ?? "") === (to.model ?? "") };
}

const ORIGIN: Record<string, string> = {
  brief: "stated in your description", answers: "from your answers", sources: "from a document you gave",
  several: "from several things you gave", inference: "the architect's inference · needs your confirmation",
  unknown: "origin not established · presented as given, but nothing given is cited",
};

/** Where an element comes from, in one phrase. Elements from before origins were recorded fall back on the basis. */
export function originLabel(i: Pick<ProposalItem, "origin" | "basis">): string {
  if (i.origin && ORIGIN[i.origin]) return ORIGIN[i.origin];
  return i.basis === "supplied" ? "from what you gave (cited)" : "inferred · needs your confirmation";
}

/** Why an element was proposed, line by line: the architect's reason, each thing it cites with the text it points
 *  to, what could not be established, and what a person decided about it. Nothing is added that was not recorded. */
export function whyLines(item: ProposalItem, proposal: Pick<Proposal, "source_index" | "decisions" | "revision">): string[] {
  const lines = [`Reason given: ${item.rationale || "none"}`, `Origin: ${originLabel(item)}`];
  const index = proposal.source_index ?? {};
  for (const e of item.evidence ?? []) {
    const src = index[e.ref];
    if (!src) { lines.push(`Cites ${e.ref} (its text is not kept with this revision)`); continue; }
    lines.push(e.kind === "answer"
      ? `Cites your answer to “${src.question || e.ref.replace("answer:", "")}”: ${src.text}`
      : e.kind === "brief" ? `Cites your description: ${src.text}` : `Cites the document ${e.ref}: ${src.text}`);
  }
  if (!(item.evidence ?? []).length) lines.push("Cites nothing that was given");
  for (const a of item.attention ?? []) lines.push(`Note: ${a}`);
  for (const d of proposal.decisions ?? []) {
    if (d.revision !== proposal.revision) continue;
    if (d.accepted.includes(item.id)) lines.push(`Accepted by ${d.decided_by} on ${d.at.slice(0, 10)}${d.note ? ` (${d.note})` : ""}`);
    if (d.rejected.includes(item.id)) lines.push(`Rejected by ${d.decided_by} on ${d.at.slice(0, 10)}${d.note ? ` (${d.note})` : ""}`);
  }
  if (typeof item.confidence === "number") lines.push(`The architect's confidence: ${item.confidence}`);
  return lines;
}

/** Where a proposal led: each draft saved from it and the releases made from that draft. */
export function outcomes(proposal: Pick<Proposal, "drafts" | "id">, releases: ReleaseRef[]): string[] {
  return (proposal.drafts ?? []).map((d) => {
    const made = releases.filter((r) => r.design?.draft_revision === d.draft_revision
      && (r.design?.proposal?.proposal ?? proposal.id) === proposal.id);
    const then = made.length ? made.map((r) => `release ${r.number} (${r.status})`).join(", ") : "not released";
    return `revision ${d.proposal_revision} → draft revision ${d.draft_revision} (saved by ${d.saved_by}) → ${then}`;
  });
}

/** What a reopened revision already decided: the elements a person accepted or rejected in it. */
export function decided(proposal: Pick<Proposal, "decisions" | "revision">): { accepted: Set<string>; rejected: Set<string> } {
  const accepted = new Set<string>(), rejected = new Set<string>();
  for (const d of proposal.decisions ?? []) {
    if (d.revision !== proposal.revision) continue;
    d.accepted.forEach((id) => { accepted.add(id); rejected.delete(id); });
    d.rejected.forEach((id) => { rejected.add(id); accepted.delete(id); });
  }
  return { accepted, rejected };
}
