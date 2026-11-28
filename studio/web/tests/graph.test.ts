import { describe, expect, it } from "vitest";
import { ontologyToGraph, relationsOf } from "../lib/graph";
import type { OntologySummary } from "../lib/types";

const o: OntologySummary = {
  ref: "t@1", fingerprint: "f", description: "",
  entities: {
    Claim: { states: ["reported", "paid"], multiple: false, aliases: [], attributes: { amount: "number" } },
    Policy: { states: [], multiple: false, aliases: [], attributes: {} },
    Holder: { states: [], multiple: true, aliases: [], attributes: { name: "string" } },
  },
  relationships: [
    { source: "Claim", target: "Policy", kind: "against", cardinality: "1" },
    { source: "Policy", target: "Holder", kind: "heldBy", cardinality: "1..*" },
    { source: "Holder", target: "Claim", kind: "files", cardinality: "0..*" },  // a cycle
    { source: "Claim", target: "Nowhere", kind: "dangling", cardinality: "1" },
  ],
  actions: {}, rules: [{ id: "R1", kind: "human_review", description: "Large Claim needs review" }],
};

describe("one model, many views", () => {
  it("projects every entity and every valid relationship, once", () => {
    const g = ontologyToGraph(o);
    expect(g.nodes.map((n) => n.id)).toEqual(["Claim", "Holder", "Policy"]);
    expect(g.edges.map((e) => e.id)).toEqual(["Claim-against-Policy", "Policy-heldBy-Holder", "Holder-files-Claim"]);
    expect(g.nodes.find((n) => n.id === "Holder")!.data.multiple).toBe(true);
  });

  it("lays out in layers and terminates on cycles", () => {
    const g = ontologyToGraph(o);
    const x = Object.fromEntries(g.nodes.map((n) => [n.id, n.position.x]));
    expect(x.Policy).toBeGreaterThan(x.Claim);
    for (const n of g.nodes) expect(Number.isFinite(n.position.x)).toBe(true);
  });

  it("gives the inspector the same relationships", () => {
    const r = relationsOf(o, "Claim");
    expect(r.outgoing.map((x) => x.kind)).toEqual(["against", "dangling"]);
    expect(r.incoming.map((x) => x.kind)).toEqual(["files"]);
    expect(r.rules.map((x) => x.id)).toEqual(["R1"]);
  });

  it("handles a 300-entity model quickly", () => {
    const big: OntologySummary = { ...o, entities: {}, relationships: [] };
    for (let i = 0; i < 300; i++) {
      big.entities[`E${i}`] = { states: [], multiple: false, aliases: [], attributes: { a: "string" } };
      if (i) big.relationships.push({ source: `E${Math.floor(i / 3)}`, target: `E${i}`, kind: "r", cardinality: "1" });
    }
    const t = performance.now();
    const g = ontologyToGraph(big);
    expect(g.nodes.length).toBe(300);
    expect(performance.now() - t).toBeLessThan(250);
  });
});
