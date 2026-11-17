// Synthetic simulation records, edited in Studio through the engine's own record API. Pure helpers: which fields an
// entity has, how a typed value is read from a form, what changed. The engine decides everything that matters: who
// may write (the data administration permission of the use case), which fields a role may set (write rules,
// decision-critical facts), whether the record changed meanwhile (revisions), and it records each write.

import type { ObjectRow } from "./runs";

export interface EntitySpec { states?: string[]; attributes?: Record<string, string> }
export interface Field { name: string; type: string; options?: string[] }

/** The fields of a record of this entity: its state first (when it has states), then its attributes. */
export function fieldsOf(spec: EntitySpec | undefined): Field[] {
  if (!spec) return [];
  const fields: Field[] = (spec.states?.length ?? 0) > 0 ? [{ name: "status", type: "state", options: spec.states }] : [];
  for (const [name, type] of Object.entries(spec.attributes ?? {})) if (name !== "status") fields.push({ name, type });
  return fields;
}

/** A form's text as the typed value the engine expects; ``error`` when it is not one. Empty means "not set". */
export function coerce(field: Field, raw: string | boolean): { value?: unknown; unset?: boolean; error?: string } {
  if (field.type === "boolean") return { value: raw === true || raw === "true" };
  const text = String(raw).trim();
  if (text === "") return field.type === "state" ? { error: `${field.name}: choose a state` } : { unset: true };
  if (field.type === "number" || field.type === "integer") {
    const n = Number(text);
    if (!Number.isFinite(n) || (field.type === "integer" && !Number.isInteger(n))) return { error: `${field.name}: a ${field.type}` };
    return { value: n };
  }
  if (field.type === "state") return field.options?.includes(text) ? { value: text } : { error: `${field.name}: one of ${field.options?.join(", ")}` };
  if (field.type === "date" && !/^\d{4}-\d{2}-\d{2}/.test(text)) return { error: `${field.name}: a date such as 2026-11-17` };
  return { value: text };
}

/** The attributes to send for a record from a form, or the problems. A record is written whole: fields the form
 *  does not show (none today) would be dropped, so every field of the entity is read. */
export function fromForm(fields: Field[], form: Record<string, string | boolean>): { attributes?: Record<string, unknown>; problems: string[] } {
  const attributes: Record<string, unknown> = {};
  const problems: string[] = [];
  for (const f of fields) {
    const out = coerce(f, form[f.name] ?? (f.type === "boolean" ? false : ""));
    if (out.error) problems.push(out.error);
    else if (!out.unset) attributes[f.name] = out.value;
  }
  return problems.length ? { problems } : { attributes, problems };
}

/** A record's values as form text. */
export function toForm(fields: Field[], row: ObjectRow | null): Record<string, string | boolean> {
  const form: Record<string, string | boolean> = {};
  for (const f of fields) {
    const v = row?.attributes?.[f.name];
    form[f.name] = f.type === "boolean" ? v === true : v === undefined || v === null ? (f.type === "state" ? f.options?.[0] ?? "" : "") : String(v);
  }
  return form;
}

/** What a save would change, field by field ("delay_minutes: 0 → 25"); empty when nothing changes. */
export function changes(row: ObjectRow | null, attributes: Record<string, unknown>): string[] {
  const before = row?.attributes ?? {};
  const names = [...new Set([...Object.keys(before), ...Object.keys(attributes)])].sort();
  const show = (v: unknown) => (v === undefined ? "not set" : JSON.stringify(v));
  return names.filter((n) => JSON.stringify(before[n]) !== JSON.stringify(attributes[n])).map((n) => `${n}: ${show(before[n])} → ${show(attributes[n])}`);
}

/** Whether records may be edited here: only where the use case holds synthetic data and cannot reach a real system. */
export function editable(stage: string): { allowed: boolean; why: string } {
  if (stage === "draft" || stage === "simulation")
    return { allowed: true, why: "Draft and Simulation hold synthetic records only; no tool can reach a real system from them." };
  return { allowed: false, why: `Records of a use case in ${stage || "this stage"} are not edited from Studio.` };
}

/** A record identifier the engine accepts and people can read. */
export const validId = (id: string): boolean => /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/.test(id);
