// Correcting one proposed element in Studio. Pure: the element's content is turned into fields a person can edit
// and back into content, by fixed rules. Nothing here is executed, and nothing here decides: the engine validates
// the corrected element like any other and records whose correction it is (autology/proposal_review.py).

export type FieldKind = "text" | "lines" | "pairs" | "flag" | "number" | "json";
export interface EditField { key: string; kind: FieldKind; text: string }

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** The fields of an element's content, in its own order. A value this editor has no plain field for is shown as
 *  JSON text, which is parsed as data and never run. */
export function fieldsOf(value: Record<string, unknown>): EditField[] {
  return Object.entries(value).map(([key, v]) => {
    if (typeof v === "string") return { key, kind: "text" as const, text: v };
    if (typeof v === "boolean") return { key, kind: "flag" as const, text: String(v) };
    if (typeof v === "number") return { key, kind: "number" as const, text: String(v) };
    if (Array.isArray(v) && v.every((x) => typeof x === "string")) return { key, kind: "lines" as const, text: v.join("\n") };
    if (isRecord(v) && Object.values(v).every((x) => typeof x === "string")) {
      return { key, kind: "pairs" as const, text: Object.entries(v).map(([k, x]) => `${k}: ${x}`).join("\n") };
    }
    return { key, kind: "json" as const, text: JSON.stringify(v, null, 1) };
  });
}

/** The content the fields describe, or what is wrong with them. The set of fields is the element's own: none can be
 *  added here, so a correction cannot introduce a property the element did not have. */
export function parseFields(fields: EditField[]): { value: Record<string, unknown> | null; problems: string[] } {
  const value: Record<string, unknown> = {};
  const problems: string[] = [];
  for (const f of fields) {
    const lines = f.text.split("\n").map((l) => l.trim()).filter(Boolean);
    if (f.kind === "text") value[f.key] = f.text.trim();
    else if (f.kind === "flag") {
      if (f.text !== "true" && f.text !== "false") problems.push(`${f.key}: yes or no`);
      value[f.key] = f.text === "true";
    } else if (f.kind === "number") {
      if (f.text.trim() === "" || !Number.isFinite(Number(f.text))) problems.push(`${f.key}: a number`);
      value[f.key] = Number(f.text);
    } else if (f.kind === "lines") value[f.key] = lines;
    else if (f.kind === "pairs") {
      const out: Record<string, string> = {};
      for (const line of lines) {
        const at = line.indexOf(":");
        const name = at < 0 ? "" : line.slice(0, at).trim();
        if (!name || !line.slice(at + 1).trim()) problems.push(`${f.key}: each line is "name: value" (${line})`);
        else if (name in out) problems.push(`${f.key}: ${name} is given twice`);
        else out[name] = line.slice(at + 1).trim();
      }
      value[f.key] = out;
    } else {
      try {
        const parsed: unknown = JSON.parse(f.text);
        if (typeof parsed !== "object" || parsed === null) problems.push(`${f.key}: a list or an object, as it was`);
        value[f.key] = parsed;
      } catch { problems.push(`${f.key}: not valid JSON`); }
    }
  }
  return { value: problems.length ? null : value, problems };
}

/** Whether the fields still describe the content they were made from (nothing to submit). */
export function unchanged(original: Record<string, unknown>, fields: EditField[]): boolean {
  const { value } = parseFields(fields);
  return value !== null && JSON.stringify(value) === JSON.stringify(original);
}

/** What changed, key by key, for the side-by-side view. */
export function changedKeys(original: Record<string, unknown>, corrected: Record<string, unknown>): string[] {
  return Object.keys({ ...original, ...corrected }).filter((k) => JSON.stringify(original[k]) !== JSON.stringify(corrected[k]));
}
