import { describe, expect, it } from "vitest";
import { addRelationship, applyItems, diffDocs, documentToSummary, removeEntity, setAttribute, setLayout } from "../lib/model";
import { ontologyToGraph } from "../lib/graph";
import type { ProposalItem } from "../lib/types";

const base = { name: "w", version: "0.1.0", entities: { Plant: { states: ["operating"], attributes: { name: "string" } } },
               relationships: [], actions: {}, rules: [] };
const item = (kind: ProposalItem["kind"], name: string | null, value: any): ProposalItem =>
  ({ id: `x:${kind}:${name}`, kind, name, value, rationale: "", status: "provisional",
     provenance: { generator: "blueprint", ai: false, matched_terms: [] } });

describe("draft model operations", () => {
  it("accepting proposal items changes a copy, never the original", () => {
    const doc = applyItems(base, [item("entity", "Pump", { states: ["running"], attributes: { tag: "string" } }),
                                  item("relationship", null, { from: "Plant", to: "Pump", type: "operates", cardinality: "1..*" })]);
    expect(Object.keys(doc.entities)).toEqual(["Plant", "Pump"]);
    expect(Object.keys(base.entities)).toEqual(["Plant"]);
    const g = ontologyToGraph(documentToSummary(doc));
    expect(g.edges.map((e) => e.id)).toEqual(["Plant-operates-Pump"]);
  });

  it("edits, removals and the diff against the saved revision", () => {
    let doc = applyItems(base, [item("entity", "Pump", { states: ["running"], attributes: { tag: "string" } })]);
    doc = addRelationship(doc, "Plant", "Pump", "operates");
    doc = setAttribute(doc, "Plant", "name", "integer");
    expect(diffDocs(base, doc).map((d) => `${d.change} ${d.kind} ${d.label}`).sort()).toEqual([
      "added entity Pump", "added relationship Plant —operates→ Pump (0..*)", "changed entity Plant"]);
    doc = removeEntity(doc, "Pump");
    expect(doc.relationships).toEqual([]);  // its relationships go with it
  });

  it("canvas positions are presentation only: they never show up as a model change", () => {
    const moved = setLayout(base, { Plant: { x: 10, y: 20 } });
    expect(moved["x-studio"].layout.Plant).toEqual({ x: 10, y: 20 });
    expect(diffDocs(base, moved)).toEqual([]);
  });
});
