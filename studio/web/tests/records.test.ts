import { describe, expect, it } from "vitest";
import { changes, coerce, editable, fieldsOf, fromForm, toForm, validId } from "../lib/records";

const TURNAROUND = { states: ["scheduled", "delayed", "completed"], attributes: { flight_number: "string", delay_minutes: "number",
  conflicts_checked: "boolean", scheduled_departure: "date", crew: "integer" } };
const fields = fieldsOf(TURNAROUND);

describe("synthetic record forms", () => {
  it("lists the state first, then every attribute with its type", () => {
    expect(fields.map((f) => `${f.name}:${f.type}`)).toEqual(["status:state", "flight_number:string", "delay_minutes:number",
      "conflicts_checked:boolean", "scheduled_departure:date", "crew:integer"]);
    expect(fields[0].options).toEqual(["scheduled", "delayed", "completed"]);
    expect(fieldsOf({ attributes: { name: "string" } }).map((f) => f.name)).toEqual(["name"]);
    expect(fieldsOf(undefined)).toEqual([]);
  });
  it("reads typed values and refuses what is not one", () => {
    const f = Object.fromEntries(fields.map((x) => [x.name, x]));
    expect(coerce(f.delay_minutes, " 25 ")).toEqual({ value: 25 });
    expect(coerce(f.delay_minutes, "soon").error).toBe("delay_minutes: a number");
    expect(coerce(f.crew, "2.5").error).toBe("crew: a integer");
    expect(coerce(f.conflicts_checked, true)).toEqual({ value: true });
    expect(coerce(f.conflicts_checked, "")).toEqual({ value: false });
    expect(coerce(f.status, "delayed")).toEqual({ value: "delayed" });
    expect(coerce(f.status, "flying").error).toContain("one of scheduled, delayed, completed");
    expect(coerce(f.status, "").error).toBe("status: choose a state");
    expect(coerce(f.scheduled_departure, "tomorrow").error).toContain("a date such as");
    expect(coerce(f.scheduled_departure, "2026-11-17")).toEqual({ value: "2026-11-17" });
    expect(coerce(f.flight_number, "")).toEqual({ unset: true });
  });
  it("builds the whole record from a form, or says every problem", () => {
    const row = { id: "T-1", type: "Turnaround", revision: 3, attributes: { status: "scheduled", flight_number: "AB123", delay_minutes: 0, conflicts_checked: false } };
    const form = toForm(fields, row);
    expect(form).toEqual({ status: "scheduled", flight_number: "AB123", delay_minutes: "0", conflicts_checked: false, scheduled_departure: "", crew: "" });
    const same = fromForm(fields, form);
    expect(same.attributes).toEqual(row.attributes);
    expect(changes(row, same.attributes!)).toEqual([]);
    const edited = fromForm(fields, { ...form, status: "delayed", delay_minutes: "25", crew: "4" });
    expect(changes(row, edited.attributes!)).toEqual(['crew: not set → 4', "delay_minutes: 0 → 25", 'status: "scheduled" → "delayed"']);
    const bad = fromForm(fields, { ...form, delay_minutes: "x", crew: "1.5" });
    expect([bad.attributes, bad.problems]).toEqual([undefined, ["delay_minutes: a number", "crew: a integer"]]);
    expect(toForm(fields, null)).toEqual({ status: "scheduled", flight_number: "", delay_minutes: "", conflicts_checked: false, scheduled_departure: "", crew: "" });
    expect(changes(null, { status: "scheduled" })).toEqual(['status: not set → "scheduled"']);
  });
  it("is offered only where the data is synthetic, and only for a sound identifier", () => {
    expect(editable("draft").allowed && editable("simulation").allowed).toBe(true);
    expect(editable("pilot")).toEqual({ allowed: false, why: "Records of a use case in pilot are not edited from Studio." });
    expect(editable("").allowed).toBe(false);
    expect([validId("T-1"), validId("turnaround:2026.1"), validId(""), validId("has space"), validId("../etc"), validId("x".repeat(81))])
      .toEqual([true, true, false, false, false, false]);
  });
});
