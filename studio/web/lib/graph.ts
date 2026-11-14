// One model, many views: the canvas and the entity list are projections of the engine's ontology summary. Node
// positions are presentation only; they never change the model.

import type { OntologySummary } from "./types";

export interface GraphNode {
  id: string;
  position: { x: number; y: number };
  data: { label: string; attributes: number; states: string[]; multiple: boolean };
  type: "entity";
}

export interface GraphEdge { id: string; source: string; target: string; label: string }

/** Layered layout: an entity sits one layer to the right of the deepest entity that points to it. */
export function ontologyToGraph(o: OntologySummary, dx = 260, dy = 120): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const names = Object.keys(o.entities).sort();
  const known = new Set(names);
  const rels = o.relationships.filter((r) => known.has(r.source) && known.has(r.target) && r.source !== r.target);
  const layer: Record<string, number> = Object.fromEntries(names.map((n) => [n, 0]));
  for (let pass = 0; pass < names.length; pass++) {  // longest-path layering, bounded (cycles stop growing)
    let changed = false;
    for (const r of rels) {
      if (layer[r.target] < layer[r.source] + 1 && layer[r.source] + 1 < names.length) {
        layer[r.target] = layer[r.source] + 1;
        changed = true;
      }
    }
    if (!changed) break;
  }
  const rows: Record<number, number> = {};
  const nodes: GraphNode[] = names.map((name) => {
    const l = layer[name];
    const row = (rows[l] = (rows[l] ?? -1) + 1);
    const e = o.entities[name];
    return { id: name, type: "entity", position: { x: l * dx, y: row * dy },
             data: { label: name, attributes: Object.keys(e.attributes).length, states: e.states, multiple: e.multiple } };
  });
  const edges: GraphEdge[] = rels.map((r) => ({ id: `${r.source}-${r.kind}-${r.target}`, source: r.source,
                                                target: r.target, label: `${r.kind} (${r.cardinality})` }));
  return { nodes, edges };
}

export function relationsOf(o: OntologySummary, entity: string) {
  return {
    outgoing: o.relationships.filter((r) => r.source === entity),
    incoming: o.relationships.filter((r) => r.target === entity),
    rules: o.rules.filter((r) => r.description.includes(entity)),
  };
}
