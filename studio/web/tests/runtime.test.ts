// The application runtime and the designer's edits: pure parts, and the boundaries the code must keep.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { basisCounts, moveNavigation, renameNavigation, setColumns, toggleNavigation } from "../lib/appdesign";
import { FORWARDED_HEADERS } from "../lib/forward";
import { call, EngineError } from "../runtime/client";
import { capabilities, cell, countBy, filterLoaded, formProblems, formRecord, graph, groupNavigation, linked, NAV_FILTER_FROM, NAV_GROUPS, outcome, runLabel, supported, timeline, unsupportedViews } from "../runtime/model";
import { DESIGN_STATES, stateWord } from "../runtime/status";
import type { Manifest, RecordRow, View } from "../runtime/types";
import { VIEW_TYPES } from "../runtime/types";

const ROOT = join(__dirname, "..");
const files = (dir: string): string[] => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  return statSync(p).isDirectory() ? files(p) : /\.(ts|tsx)$/.test(p) ? [p] : [];
});
const RUNTIME = files(join(ROOT, "runtime"));

const list: View = { id: "list-thing", type: "EntityListView", title: "Thing", basis: "ontology", entity: "Thing",
  columns: [{ field: "status", label: "Status", basis: "ontology" }, { field: "label", label: "Label", basis: "default" }] };
const manifest: Manifest = { manifest_version: 1, id: "a", title: "A", binding: { model: "m@1", model_fingerprint: "f", configuration: "c", engine_api: "1" },
  roles: [], navigation: [{ view: "list-thing", label: "Thing", basis: "default" }, { view: "audit", label: "Audit", basis: "default" }],
  views: [list, { id: "audit", type: "AuditTimelineView", title: "Audit", basis: "default" }, { id: "detail-thing", type: "EntityDetailView", title: "Thing", basis: "ontology", entity: "Thing", fields: [] }],
  unavailable: [], presentation: { accent: "blue", density: "comfortable" } };
const rows: RecordRow[] = [{ id: "T-1", type: "Thing", attributes: { status: "open", label: "Alpha" } },
  { id: "T-2", type: "Thing", attributes: { status: "closed", label: "Beta" } }, { id: "T-3", type: "Thing", attributes: { status: "open", label: null } }];

describe("the runtime is a renderer and nothing else", () => {
  it("is separate from Studio: it imports nothing of Studio's, and Studio embeds it in the designer only", () => {
    expect(RUNTIME.length).toBeGreaterThanOrEqual(5);
    for (const f of RUNTIME) expect(readFileSync(f, "utf8"), f).not.toMatch(/from ["']@\/(components|lib)\//);
    const users = files(join(ROOT, "components")).filter((f) => /from ["']@\/runtime\/RuntimeApp["']/.test(readFileSync(f, "utf8")));
    expect(users.map((f) => f.split("/").pop())).toEqual(["ApplicationDesigner.tsx"]);
    const page = readFileSync(join(ROOT, "app", "run", "[workspace]", "[useCase]", "page.tsx"), "utf8");
    expect(page).not.toMatch(/@\/components|@\/lib/);
  });

  it("never turns data into markup or code, and keeps no token beyond the tab", () => {
    for (const f of RUNTIME) {
      const src = readFileSync(f, "utf8");
      expect(src, f).not.toMatch(/dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML|document\.write/);
      expect(src, f).not.toMatch(/\beval\s*\(|new Function|setTimeout\s*\(\s*["'`]/);
      expect(src, f).not.toMatch(/localStorage|document\.cookie/);
      expect(src, f).not.toMatch(/<a\s|href=|src=|window\.open|location\.(href|assign|replace)/);  // no address comes from a manifest
      expect(src, f).not.toMatch(/https?:\/\//);
    }
  });

  it("asks only the Engine's API of its own use case, and is opened from Studio in a tab that shares no session", () => {
    for (const f of RUNTIME) expect(readFileSync(f, "utf8").split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n"), f).not.toMatch(/["'`]\/platform|\/platform\//);
    const shell = readFileSync(join(ROOT, "runtime", "RuntimeApp.tsx"), "utf8");
    expect(shell).toMatch(/const base = enginePath\(workspace, useCase\);/);
    expect(shell.match(/\bbase\b[^;\n]*=/g)).toHaveLength(1);  // one address, set once, from the page's own workspace and use case
    expect(readFileSync(join(ROOT, "runtime", "client.ts"), "utf8")).toContain("`/w/${encodeURIComponent(workspace)}/u/${encodeURIComponent(useCase)}/api/v1`");
    const designer = readFileSync(join(ROOT, "components", "ApplicationDesigner.tsx"), "utf8");
    const link = designer.split("\n").find((l) => l.includes("data-testid=\"app-open\"")) ?? "";
    expect(link).toMatch(/target="_blank"/);
    expect(link).toMatch(/rel="noreferrer"/);  // no opener: the new tab does not inherit Studio's session storage
  });

  it("has its own token, apart from Studio's", () => {
    expect(readFileSync(join(ROOT, "runtime", "client.ts"), "utf8")).toContain("autology-app-token");
    expect(readFileSync(join(ROOT, "lib", "api.ts"), "utf8")).toContain("autology-studio-token");
    for (const f of RUNTIME) expect(readFileSync(f, "utf8"), f).not.toContain("autology-studio-token");
  });

  it("holds no word of a domain", () => {
    const words = /flood|incident|shelter|hazard|evacuat|fraud|invoice|compliance|investigat|bank|booking|venue|room\b/i;
    for (const f of [...RUNTIME, join(ROOT, "lib", "appdesign.ts"), join(ROOT, "components", "ApplicationDesigner.tsx")]) {
      const hit = readFileSync(f, "utf8").split("\n").find((line) => words.test(line));
      expect(hit, f).toBeUndefined();
    }
  });

  it("renders the view types of the schema and no other", () => {
    expect([...VIEW_TYPES].sort()).toEqual(["ApprovalInboxView", "AuditTimelineView", "DashboardView", "EntityDetailView",
      "EntityListView", "RecordFormView", "RelationshipView", "WorkflowView"]);
    const shell = readFileSync(join(ROOT, "runtime", "RuntimeApp.tsx"), "utf8");
    for (const t of VIEW_TYPES) expect(shell).toContain(`case "${t}"`);
    expect(supported({ type: "ScriptView" })).toBe(false);
    expect(unsupportedViews({ views: [list, { ...list, id: "x", type: "MapView" }] }).map((v) => v.type)).toEqual(["MapView"]);
  });
});

describe("the menu and what a person can do", () => {
  const views = [{ id: "o", type: "DashboardView" }, { id: "w", type: "WorkflowView" }, { id: "l1", type: "EntityListView" },
    { id: "l2", type: "EntityListView" }, { id: "i", type: "ApprovalInboxView" }, { id: "a", type: "AuditTimelineView" }, { id: "x", type: "MapView" }];
  const nav = [["l2", "Zeta"], ["a", "Audit"], ["o", "Overview"], ["l1", "Alpha"], ["i", "Decisions"], ["w", "Work"], ["x", "Map"]]
    .map(([view, label]) => ({ view, label, basis: "default" as const }));

  it("groups screens by view type, keeps the designer's order inside a group and loses none it can render", () => {
    expect(groupNavigation(nav, views).map((g) => [g.label, g.items.map((n) => n.view)])).toEqual([
      ["Overview", ["o"]], ["Work", ["i", "w"]], ["Records", ["l2", "l1"]], ["Evidence", ["a"]]]);
    expect(NAV_GROUPS.flatMap(([, types]) => types).sort()).toEqual([...VIEW_TYPES].sort());  // every view type has a group
    expect(groupNavigation(nav, views, " ALP ").map((g) => [g.label, g.items.map((n) => n.label)])).toEqual([["Records", ["Alpha"]]]);
    expect(groupNavigation(nav, views, "zz")).toEqual([]);
    expect(NAV_FILTER_FROM).toBeGreaterThan(5);
    const source = readFileSync(join(ROOT, "runtime", "model.ts"), "utf8");
    expect(source).not.toMatch(/label\.(includes|startsWith|match)\(["'`][A-Za-z]/);  // no screen is grouped by what it is called
  });

  it("words what the Engine allows, and never adds to it", () => {
    const none = { read_records: false, start_runs: false, decide_reviews: false, read_audit: false, write_records: false };
    expect(capabilities(none).can).toEqual([]);
    expect(capabilities(none).cannot).toHaveLength(5);
    const some = capabilities({ ...none, read_records: true, start_runs: true });
    expect(some.can).toEqual(["Read records, within the rules of the model", "Ask the solution to handle a record"]);
    expect(some.cannot.map((c) => c.what)).toEqual(["Decide reviews addressed to your reviewer roles", "Read the audit trail of a request", "Create or change records"]);
    expect(some.cannot[2].why).toContain("owner decision D24");
    expect(capabilities({ read_records: true, start_runs: true, decide_reviews: true, read_audit: true, write_records: true }).cannot).toEqual([]);
  });

  it("tells the screen when the Engine last answered, on success only", async () => {
    let heard = 0;
    const ok = (async () => new Response("{}", { status: 200 })) as unknown as typeof fetch;
    const no = (async () => new Response('{"error":{"message":"no"}}', { status: 403 })) as unknown as typeof fetch;
    const who = { base: "/w/a/u/b/api/v1", token: () => "t", heard: () => { heard += 1; } };
    await call(who, "GET", "/me", undefined, ok);
    await expect(call(who, "GET", "/me", undefined, no)).rejects.toBeInstanceOf(EngineError);
    expect(heard).toBe(1);
  });
});

describe("what a design is said to be", () => {
  it("has the Engine's six states, in order, and three words for them", () => {
    expect(DESIGN_STATES.map(([key]) => key)).toEqual(["design_draft", "validated_design", "configuration_bound",
      "approved_release_artifact", "simulation_ready", "production_authorized"]);
    expect([stateWord({ supported: true, value: true }), stateWord({ supported: true, value: false }),
      stateWord({ supported: false, value: false }), stateWord({ supported: false, value: true })]).toEqual(["yes", "no", "not supported", "not supported"]);
  });

  it("is never worded by a screen as released, deployed or in production", () => {
    for (const f of [...RUNTIME, join(ROOT, "lib", "appdesign.ts"), join(ROOT, "components", "ApplicationDesigner.tsx")]) {
      const text = readFileSync(f, "utf8").split("\n").filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line)).join("\n");
      expect(text, f).not.toMatch(/\b(deployed|published|operational|go(es)? live|is live|released application|application release)\b/i);
      // production is named only to say it is unavailable, or as the Engine's state that is not supported
      const said = text.split("\n").filter((line) => /production/i.test(line));
      for (const line of said) expect(line, f).toMatch(/Production: unavailable|"Production authorized"|production_authorized|production: boolean/);
    }
  });
});

describe("the runtime's client", () => {
  it("names the configuration it was read for, and the relay forwards exactly that header besides the two it had", async () => {
    expect(FORWARDED_HEADERS).toEqual(["authorization", "content-type", "x-autology-configuration"]);
    let seen: Record<string, string> = {};
    const fake = (async (_url: RequestInfo | URL, init?: RequestInit) => {
      seen = init?.headers as Record<string, string>;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    await call({ base: "/w/a/u/b/api/v1", token: () => "t", configuration: "abc" }, "GET", "/objects", undefined, fake);
    expect(seen).toEqual({ Authorization: "Bearer t", "X-Autology-Configuration": "abc" });
    await call({ base: "/w/a/u/b/api/v1", token: () => "t" }, "GET", "/objects", undefined, fake);
    expect(seen).toEqual({ Authorization: "Bearer t" });
  });

  it("reports the engine's refusal with its details", async () => {
    const refuse = (async () => new Response(JSON.stringify({ error: { status: 409, message: "another configuration", details: { running: "r" } } }), { status: 409 })) as typeof fetch;
    await expect(call({ base: "", token: () => "t" }, "GET", "/application", undefined, refuse)).rejects.toMatchObject(
      { status: 409, message: "another configuration", details: { running: "r" } });
    expect(new EngineError(404, "x")).toBeInstanceOf(Error);
  });
});

describe("what the screens compute", () => {
  it("shows values as text", () => {
    expect([cell(null), cell(""), cell(true), cell(false), cell(3), cell("<b>x</b>"), cell({ a: 1 })]).toEqual(["—", "—", "yes", "no", "3", "<b>x</b>", '{"a":1}']);
  });
  it("filters the loaded page only, and counts what was loaded", () => {
    expect(filterLoaded(rows, "alp", list.columns ?? []).map((r) => r.id)).toEqual(["T-1"]);
    expect(filterLoaded(rows, "t-2", list.columns ?? []).map((r) => r.id)).toEqual(["T-2"]);
    expect(filterLoaded(rows, "  ", list.columns ?? []).length).toBe(3);
    expect(countBy(rows)).toEqual([["open", 2], ["closed", 1]]);
  });
  it("draws recorded links only", () => {
    const record: RecordRow = { id: "T-1", type: "Thing", attributes: {}, links: [
      { kind: "owns", direction: "out", id: "P-2", type: "Part" }, { kind: "owns", direction: "out", id: "P-1", type: "Part" },
      { kind: "made_by", direction: "in", id: "M-1", type: "Maker" }] };
    const g = graph(record);
    expect(g.nodes.map((n) => n.id)).toEqual(["T-1", "M-1", "P-1", "P-2"]);
    expect(g.edges).toEqual([{ from: "M-1", to: "T-1", label: "made_by" }, { from: "T-1", to: "P-1", label: "owns" }, { from: "T-1", to: "P-2", label: "owns" }]);
    expect(graph({ id: "T-9", type: "Thing", attributes: {} }).edges).toEqual([]);
    expect(graph({ ...record, links: Array.from({ length: 30 }, (_, i) => ({ kind: "k", direction: "out" as const, id: `X-${i}`, type: "X" })) }).omitted).toBe(6);
    expect(linked(record, { relationship: "owns", direction: "out", entity: "Part", label: "", basis: "ontology" }).map((x) => x.id)).toEqual(["P-1", "P-2"]);
    expect(linked(record, { relationship: "owns", direction: "in", entity: "Part", label: "", basis: "ontology" })).toEqual([]);
  });
  it("checks a form's shape for comfort and leaves validation to the engine", () => {
    const form: View = { id: "f", type: "RecordFormView", title: "New", basis: "default", entity: "Thing", fields: [
      { field: "status", label: "Status", basis: "ontology", input: "select", options: ["open", "closed"] },
      { field: "size", label: "Size", basis: "ontology", input: "number" }, { field: "urgent", label: "Urgent", basis: "ontology", input: "checkbox" },
      { field: "label", label: "Label", basis: "ontology", input: "text" }] };
    expect(formProblems(form, { size: "abc", status: "gone" })).toEqual(["Status: one of open, closed", "Size: a number"]);
    expect(formProblems(form, { size: "4", status: "open" })).toEqual([]);
    expect(formRecord(form, { size: "4", status: "open", urgent: "true", label: " x " })).toEqual({ status: "open", size: 4, urgent: true, label: "x" });
  });
  it("tells a refusal by policy from a wait and from an ordinary stop", () => {
    expect(outcome({ status: "escalated", escalation: { reason: "no compliant path to the goal", details: ["do_it: prohibited: never on Sundays"] } }))
      .toBe("Refused by policy: do_it: prohibited: never on Sundays");
    expect(outcome({ status: "awaiting_review", escalation: { reason: "awaiting lead review of do_it", details: ["A lead decides"] } }))
      .toBe("Waiting for a person: awaiting lead review of do_it (A lead decides)");
    expect(outcome({ status: "escalated", escalation: { reason: "do_it failed 3 times: outage", details: [] } })).toBe("Stopped: do_it failed 3 times: outage");
    expect(outcome({ status: "completed" })).toBe("Completed");
    expect(runLabel({ status: "escalated", escalation: { reason: "x", details: ["do_it: prohibited: never"] } })).toBe("Refused by policy");
    expect(runLabel({ status: "escalated", escalation: { reason: "do_it failed 3 times", details: [] } })).toBe("Stopped by the Engine");
  });
  it("reads the engine's chain as lines, and invents none", () => {
    const lines = timeline([{ seq: 1, event: "run.start", data: { acting_as: "ann", agent: "a", goal: "g" } },
      { seq: 2, event: "internal.key", data: {} }, { seq: 3, event: "review.decision", data: { action: "do_it", approved: true, reviewer: "lea", comment: "ok" } }]);
    expect(lines.map((l) => [l.seq, l.label])).toEqual([[1, "Run started"], [3, "A person decided"]]);
    expect(lines[1].detail).toBe("do_it: approved by lea — ok");
  });
});

describe("the designer's edits", () => {
  it("arranges screens and marks what a person changed", () => {
    const columns = setColumns(manifest, "list-thing", ["label", "status", "size"]);
    expect(columns.views[0].columns?.map((c) => [c.field, c.basis, c.label])).toEqual(
      [["label", "confirmed", "Label"], ["status", "confirmed", "Status"], ["size", "confirmed", "Size"]]);
    expect(manifest.views[0].columns?.length).toBe(2);  // the design given is not changed in place
    const hidden = toggleNavigation(manifest, "audit");
    expect(hidden.navigation.map((n) => n.view)).toEqual(["list-thing"]);
    expect(toggleNavigation(hidden, "detail-thing").navigation.at(-1)).toEqual({ view: "detail-thing", label: "Thing", basis: "confirmed" });
    expect(moveNavigation(manifest, "audit", -1).navigation.map((n) => [n.view, n.basis])).toEqual([["audit", "confirmed"], ["list-thing", "default"]]);
    expect(moveNavigation(manifest, "audit", 1)).toBe(manifest);
    expect(renameNavigation(manifest, "audit", "Trail").navigation[1]).toEqual({ view: "audit", label: "Trail", basis: "confirmed" });
    expect(basisCounts(manifest)).toEqual({ ontology: 3, configuration: 0, default: 4, confirmed: 0, unresolved: 0 });
  });
  it("cannot express a permission, a rule or code: the manifest type has no place for one", () => {
    const keys = new Set(Object.keys(setColumns(toggleNavigation(manifest, "audit"), "list-thing", ["status"])));
    expect([...keys].sort()).toEqual(["binding", "id", "manifest_version", "navigation", "presentation", "roles", "title", "unavailable", "views"]);
    const designer = readFileSync(join(ROOT, "components", "ApplicationDesigner.tsx"), "utf8");
    expect(designer).not.toMatch(/dangerouslySetInnerHTML|eval\(|new Function/);
  });
});
