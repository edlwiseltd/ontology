// The Application Designer's pure edits on a manifest (autology/appspec.py). A designer arranges what the generator
// proposed: which screens are in the navigation, in which order, under which label, and which attributes a list
// shows. Nothing here can add a permission, a rule or an expression: the Engine validates every result.
import type { Basis, Field, Manifest, View } from "@/runtime/types";

export const BASIS_TEXT: Record<Basis, string> = {
  ontology: "from the model", configuration: "from the approved configuration", default: "a presentation default",
  confirmed: "confirmed by a person", unresolved: "unresolved: a person must decide" };

export const words = (name: string): string => {
  const spaced = name.replace(/[_-]/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2").trim();
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1).toLowerCase() : name;
};

export function basisCounts(manifest: Manifest): Record<Basis, number> {
  const out: Record<Basis, number> = { ontology: 0, configuration: 0, default: 0, confirmed: 0, unresolved: 0 };
  const count = (b: Basis) => { out[b] = (out[b] ?? 0) + 1; };
  for (const n of manifest.navigation) count(n.basis);
  for (const v of manifest.views) {
    count(v.basis);
    if (v.agent) count(v.agent.basis);
    for (const key of ["columns", "fields", "related", "actions", "tiles"] as const) for (const c of v[key] ?? []) count(c.basis);
  }
  return out;
}

const withView = (m: Manifest, id: string, change: (v: View) => View): Manifest =>
  ({ ...m, views: m.views.map((v) => (v.id === id ? change(v) : v)) });

/** The attributes a list shows, in the order given. A column the person chose is "confirmed". */
export function setColumns(m: Manifest, viewId: string, fields: string[]): Manifest {
  return withView(m, viewId, (v) => {
    const before = new Map((v.columns ?? []).map((c) => [c.field, c]));
    const columns: Field[] = fields.map((f) => ({ field: f, label: before.get(f)?.label ?? (f === "status" ? "Status" : words(f)), basis: "confirmed" }));
    return { ...v, columns, basis: "confirmed" };
  });
}

export function inNavigation(m: Manifest, viewId: string): boolean { return m.navigation.some((n) => n.view === viewId); }

export function toggleNavigation(m: Manifest, viewId: string): Manifest {
  if (inNavigation(m, viewId)) return { ...m, navigation: m.navigation.filter((n) => n.view !== viewId) };
  const view = m.views.find((v) => v.id === viewId);
  return view ? { ...m, navigation: [...m.navigation, { view: viewId, label: view.title, basis: "confirmed" }] } : m;
}

export function moveNavigation(m: Manifest, viewId: string, by: -1 | 1): Manifest {
  const i = m.navigation.findIndex((n) => n.view === viewId), j = i + by;
  if (i < 0 || j < 0 || j >= m.navigation.length) return m;
  const next = m.navigation.slice();
  [next[i], next[j]] = [{ ...next[j] }, { ...next[i], basis: "confirmed" }];
  return { ...m, navigation: next };
}

export function renameNavigation(m: Manifest, viewId: string, label: string): Manifest {
  return { ...m, navigation: m.navigation.map((n) => (n.view === viewId ? { ...n, label, basis: "confirmed" } : n)) };
}

export const setTitle = (m: Manifest, title: string): Manifest => ({ ...m, title });
export const setAccent = (m: Manifest, accent: string): Manifest => ({ ...m, presentation: { ...m.presentation, accent } });
export const ACCENTS = ["blue", "teal", "green", "amber", "violet", "slate"];

/** What each screen is about, for the designer's table. */
export function describe(view: View): string {
  const parts = [view.entity ? `records of ${view.entity}` : "",
    view.columns ? `${view.columns.length} column(s)` : "", view.fields ? `${view.fields.length} field(s)` : "",
    view.related?.length ? `${view.related.length} relationship(s)` : "", view.actions ? `${view.actions.length} action(s)` : "",
    view.case_template ? `case ${view.case_template}` : "", view.agent ? `agent ${view.agent.name}` : "",
    view.rules ? `${view.rules.length} review rule(s)` : "", view.tiles ? `${view.tiles.length} tile(s)` : ""];
  return parts.filter(Boolean).join(" · ");
}
