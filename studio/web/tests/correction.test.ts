// Correcting a proposed element in Studio: fields from content and content from fields, by fixed rules.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { changedKeys, fieldsOf, parseFields, unchanged } from "../lib/correction";

const entity = { description: "A piece of work", states: ["open", "done"], attributes: { title: "string", size: "number" } };
const action = { description: "Finish", capability: "ops.finish", requires: ["Thing.status == 'open'"],
  effects: { Thing: { status: "done" } }, side_effect: "none" };
const relationship = { from: "A", to: "B", type: "owns", cardinality: "1..*" };

describe("the fields of a correction", () => {
  it("come from the element's own content, in its order, and give it back unchanged", () => {
    expect(fieldsOf(entity).map((f) => [f.key, f.kind])).toEqual([["description", "text"], ["states", "lines"], ["attributes", "pairs"]]);
    expect(fieldsOf(action).map((f) => f.kind)).toEqual(["text", "text", "lines", "json", "text"]);
    for (const value of [entity, action, relationship, { flag: true, count: 3, nested: [{ a: 1 }] }]) {
      expect(parseFields(fieldsOf(value))).toEqual({ value, problems: [] });
      expect(unchanged(value, fieldsOf(value))).toBe(true);
    }
  });

  it("turn edits into content, and say what changed", () => {
    const fields = fieldsOf(entity).map((f) => f.key === "states" ? { ...f, text: "open\n done \n\narchived" }
      : f.key === "attributes" ? { ...f, text: "title: string\nsize: number\nnote: string" } : f);
    const { value, problems } = parseFields(fields);
    expect(problems).toEqual([]);
    expect(value).toEqual({ description: "A piece of work", states: ["open", "done", "archived"], attributes: { title: "string", size: "number", note: "string" } });
    expect(changedKeys(entity, value!)).toEqual(["states", "attributes"]);
    expect(unchanged(entity, fields)).toBe(false);
  });

  it("refuse what they cannot read, and submit nothing then", () => {
    const bad = (key: string, text: string, source: Record<string, unknown> = { ...entity, flag: true, count: 1, nested: { a: [1] } }) =>
      parseFields(fieldsOf(source).map((f) => (f.key === key ? { ...f, text } : f)));
    expect(bad("attributes", "title string")).toEqual({ value: null, problems: ['attributes: each line is "name: value" (title string)'] });
    expect(bad("attributes", "title: string\ntitle: number").problems).toEqual(["attributes: title is given twice"]);
    expect(bad("flag", "maybe").problems).toEqual(["flag: yes or no"]);
    expect(bad("count", "many").problems).toEqual(["count: a number"]);
    expect(bad("nested", "{not json").problems).toEqual(["nested: not valid JSON"]);
    expect(bad("nested", '"a string"').problems).toEqual(["nested: a list or an object, as it was"]);
    expect(unchanged(entity, fieldsOf(entity).map((f) => ({ ...f, text: f.key === "attributes" ? "x" : f.text })))).toBe(false);
  });

  it("cannot add a property the element did not have, and run nothing", () => {
    const fields = fieldsOf(relationship);
    expect(Object.keys(parseFields(fields).value!)).toEqual(Object.keys(relationship));       // the set of fields is the element's
    const source = readFileSync(join(__dirname, "..", "lib", "correction.ts"), "utf8") + readFileSync(join(__dirname, "..", "components", "ElementEditor.tsx"), "utf8");
    expect(source).not.toMatch(/\beval\s*\(|new Function|dangerouslySetInnerHTML|innerHTML/);
    expect(source).not.toMatch(/architect\.|fetch\(/);   // the editor sends nothing itself: the screen calls the engine's decision route
  });
});
