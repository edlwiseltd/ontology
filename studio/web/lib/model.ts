// Pure operations on a draft model document (no I/O). Every edit returns a new document; the engine validates it.
// Canvas positions live under "x-studio".layout: presentation metadata the strict schema ignores ("x-" keys).

import type { ModelDocument, OntologySummary, ProposalItem } from "./types";

export const ATTRIBUTE_TYPES = ["string", "number", "integer", "boolean", "date", "datetime"];

const clone = (d: ModelDocument): ModelDocument => JSON.parse(JSON.stringify(d ?? {}));
const typeOf = (spec: any): string => (typeof spec === "string" ? spec : spec?.type ?? "string");

/** The engine's ontology-summary shape, so the same graph projection serves the active model and drafts. */
export function documentToSummary(doc: ModelDocument): OntologySummary {
  const entities: OntologySummary["entities"] = {};
  for (const [name, e] of Object.entries<any>(doc.entities ?? {})) {
    entities[name] = { states: e?.states ?? [], multiple: !!e?.multiple, aliases: e?.aliases ?? [],
      attributes: Object.fromEntries(Object.entries(e?.attributes ?? {}).map(([a, s]) => [a, typeOf(s)])) };
  }
  return {
    ref: `${doc.name ?? "draft"}@${doc.version ?? "?"}`, fingerprint: "", description: doc.description ?? "", entities,
    relationships: (doc.relationships ?? []).filter((r: any) => r && typeof r === "object")
      .map((r: any) => ({ source: r.from, target: r.to, kind: r.type, cardinality: r.cardinality ?? "1..*" })),
    actions: doc.actions ?? {}, rules: (doc.rules ?? []).map((r: any) => ({ id: r.id, kind: r.type, description: r.description ?? "" })),
  };
}

export function applyItems(doc: ModelDocument, items: ProposalItem[]): ModelDocument {
  const d = clone(doc);
  for (const item of items) {
    if (item.kind === "entity") (d.entities ??= {})[item.name!] = item.value;
    else if (item.kind === "action") (d.actions ??= {})[item.name!] = item.value;
    else if (item.kind === "relationship") (d.relationships ??= []).push(item.value);
    else if (item.kind === "rule") (d.rules ??= []).push(item.value);
  }
  return d;
}

export function addEntity(doc: ModelDocument, name: string): ModelDocument {
  const d = clone(doc);
  (d.entities ??= {})[name] = { description: "", states: ["active"], attributes: { name: "string" } };
  return d;
}

export function removeEntity(doc: ModelDocument, name: string): ModelDocument {
  const d = clone(doc);
  delete d.entities?.[name];
  d.relationships = (d.relationships ?? []).filter((r: any) => r.from !== name && r.to !== name);
  return d;
}

export function setEntityField(doc: ModelDocument, name: string, field: "description" | "states", value: string): ModelDocument {
  const d = clone(doc);
  const e = d.entities[name];
  if (field === "description") e.description = value;
  else e.states = value.split(",").map((s) => s.trim()).filter(Boolean);
  return d;
}

export function setAttribute(doc: ModelDocument, entity: string, attr: string, type: string): ModelDocument {
  const d = clone(doc);
  const attrs = (d.entities[entity].attributes ??= {});
  const old = attrs[attr];
  attrs[attr] = typeof old === "object" && old !== null ? { ...old, type } : type;
  return d;
}

export function removeAttribute(doc: ModelDocument, entity: string, attr: string): ModelDocument {
  const d = clone(doc);
  delete d.entities[entity].attributes?.[attr];
  return d;
}

export function addRelationship(doc: ModelDocument, from: string, to: string, type = "relatedTo", cardinality = "0..*"): ModelDocument {
  const d = clone(doc);
  (d.relationships ??= []).push({ from, to, type, cardinality });
  return d;
}

export function updateRelationship(doc: ModelDocument, index: number, patch: { type?: string; cardinality?: string }): ModelDocument {
  const d = clone(doc);
  d.relationships[index] = { ...d.relationships[index], ...patch };
  return d;
}

export function removeRelationship(doc: ModelDocument, index: number): ModelDocument {
  const d = clone(doc);
  d.relationships.splice(index, 1);
  return d;
}

export function setLayout(doc: ModelDocument, positions: Record<string, { x: number; y: number }>): ModelDocument {
  const d = clone(doc);
  d["x-studio"] = { ...(d["x-studio"] ?? {}), layout: positions };
  return d;
}

export interface DiffEntry { kind: "entity" | "relationship" | "action" | "rule"; change: "added" | "removed" | "changed"; label: string }

/** What changed between the saved revision and the working copy (layout excluded: presentation only). */
export function diffDocs(saved: ModelDocument, working: ModelDocument): DiffEntry[] {
  const out: DiffEntry[] = [];
  const keyed = (kind: DiffEntry["kind"], a: Record<string, any> = {}, b: Record<string, any> = {}) => {
    for (const k of Object.keys(b)) if (!(k in a)) out.push({ kind, change: "added", label: k });
    for (const k of Object.keys(a)) if (!(k in b)) out.push({ kind, change: "removed", label: k });
    for (const k of Object.keys(b)) if (k in a && JSON.stringify(a[k]) !== JSON.stringify(b[k])) out.push({ kind, change: "changed", label: k });
  };
  keyed("entity", saved.entities, working.entities);
  keyed("action", saved.actions, working.actions);
  const rel = (r: any) => `${r.from} —${r.type}→ ${r.to} (${r.cardinality ?? "1..*"})`;
  keyed("relationship", Object.fromEntries((saved.relationships ?? []).map((r: any) => [rel(r), r])),
        Object.fromEntries((working.relationships ?? []).map((r: any) => [rel(r), r])));
  keyed("rule", Object.fromEntries((saved.rules ?? []).map((r: any) => [r.id ?? JSON.stringify(r), r])),
        Object.fromEntries((working.rules ?? []).map((r: any) => [r.id ?? JSON.stringify(r), r])));
  return out;
}
