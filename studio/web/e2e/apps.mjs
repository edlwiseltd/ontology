// Application Builder browser tests: for three unrelated synthetic solutions, the same designer (in Studio) and the
// same renderer (the application runtime, at its own address) are driven by the same function. Only the table
// below differs. The solutions are released and in Simulation before this starts (e2e/prepare_apps.py).
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw;
try { pw = require("playwright"); } catch { pw = require("/opt/node22/lib/node_modules/playwright"); }
const STUDIO = process.env.STUDIO_URL ?? "http://127.0.0.1:8963";
const OUT = process.env.SHOTS ?? "e2e/screenshots";
mkdirSync(OUT, { recursive: true });
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };

const APPS = {
  crisis: { uc: "flood", name: "crisis demonstrator", admin: "carla", approver: "rosa", operator: "omar", reviewer: "dana",
            accent: "amber", root: "IncidentReport", roots: 5, alone: "INC-2001", refused: "INC-2003", waits: "INC-2002", hiddenLabel: null },
  netintel: { uc: "cases", name: "netintel demonstrator", admin: "nora", approver: "ravi", operator: "alan", reviewer: "cleo",
              accent: "violet", root: "CaseFile", roots: 3, alone: "CASE-3001", refused: "CASE-3003", waits: "CASE-3002", hiddenLabel: "Bank account",
              lists: [["Association", ["observed_fact", "confirmed_assertion", "inference", "unresolved_hypothesis"]],
                      ["Hypothesis", ["freight agent"]], ["Evidence", ["unverified", "primary"]]] },
  venues: { uc: "bookings", name: "Bookings", admin: "vera", approver: "vito", operator: "viv", reviewer: "val",
            accent: "teal", root: "BookingRequest", roots: 3, alone: "BKG-4001", refused: "BKG-4003", waits: "BKG-4002", hiddenLabel: null },
};
const words = (n) => { const s = n.replace(/[_-]/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2").trim(); return s[0].toUpperCase() + s.slice(1).toLowerCase(); };

const browser = await pw.chromium.launch();
const errors = [];
const page = async (viewport = { width: 1280, height: 900 }) => { const p = await browser.newPage({ viewport }); p.on("pageerror", (e) => errors.push(String(e))); return p; };
const states = (p, id) => p.$$eval(`[data-testid=${id}] li`, (els) => Object.fromEntries(els.map((e) => [e.dataset.state, e.dataset.value])));
const AS_DESIGNED = { design_draft: "yes", validated_design: "yes", configuration_bound: "yes", approved_release_artifact: "not supported",
  simulation_ready: "yes", production_authorized: "not supported" };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const noScroll = (p) => p.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);

async function demo(ws) {
  const d = APPS[ws];
  const say = (name, ok, detail) => check(`${ws}: ${name}`, ok, detail);
  const token = (who) => `${ws}-${who}`;
  const ENG = `/w/${ws}/u/${d.uc}/api/v1`, UC = `/platform/v1/workspaces/${ws}/use-cases/${d.uc}`;
  const steps = [];

  // ---- the application does not exist until it is designed
  const app = await page();
  const as = (who, method, path, body, extra = {}) => app.evaluate(async ([t, m, u, b, h]) => {
    const r = await fetch(u, { method: m, headers: { ...(t ? { Authorization: "Bearer " + t } : {}), "Content-Type": "application/json", ...h },
                               body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, body: await r.json().catch(() => ({})) };
  }, [who && (who.includes("-") ? who : token(who)), method, path, body, extra]);
  await app.goto(`${STUDIO}/run/${ws}/${d.uc}`);
  await app.waitForSelector("[data-testid=rt-signin]");
  await app.fill("#rt-token", token(d.operator));
  await app.click("form button[type=submit]");
  await app.waitForSelector("[data-testid=rt-refused]");
  say("before any design the runtime shows nothing and says why",
      (await app.textContent("[data-testid=rt-refusal]")).includes("no application has been designed"));
  const generated = (await as(d.admin, "POST", `${ENG}/application/generate`, {})).body.manifest;
  const listView = generated.views.find((v) => v.type === "EntityListView" && v.entity === d.root);
  const dropped = listView.columns.at(-1);

  // ---- Studio: the Application Designer
  const studio = await page();
  await studio.goto(STUDIO);
  await studio.fill("#token", token(d.admin));
  await studio.click("form button[type=submit]");
  await studio.waitForSelector(`.uc-list button:has-text('${d.name}')`);
  await studio.click(`.uc-list button:has-text('${d.name}')`);
  await studio.click("role=tab[name='Application']");
  await studio.waitForSelector("[data-testid=app-designer]");
  say("the designer starts from what is released and says it holds no rule, permission or code",
      (await studio.textContent("[data-testid=app-notice]")).includes("what is released") &&
      (await studio.textContent("[data-testid=app-state]")).includes("No design saved yet"));
  await studio.click("[data-testid=app-generate]");
  await studio.waitForSelector("[data-testid=app-screens] tbody tr");
  steps.push("select", "generate");
  say("a specification is generated by the engine, deterministically, and no language model is asked",
      (await studio.textContent("[data-testid=app-message]")).includes("no language model") &&
      (await studio.textContent("[data-testid=app-validation]")).includes("accepts") &&
      (await studio.locator("[data-testid=app-screens] tbody tr").count()) === generated.views.length,
      `${generated.views.length} screens, ${generated.navigation.length} in navigation`);
  const basisText = await studio.textContent("[data-testid=app-basis]");
  say("every choice says where it comes from: the model, the approved configuration, or a presentation default nobody confirmed",
      basisText.includes("from the model") && basisText.includes("1 from the approved configuration") &&
      basisText.includes("a presentation default") && !basisText.includes("confirmed by a person"), basisText.slice(0, 140));
  await studio.click(`tr[data-view=${listView.id}] button.link`);
  await studio.waitForSelector("[data-testid=app-columns]");
  await studio.uncheck(`[data-testid=app-columns] input[data-column=${dropped.field}]`);
  await studio.fill(`input[aria-label='Label of ${listView.id}']`, `${words(d.root)} (all)`);
  await studio.fill("#app-title", `${generated.title} desk`);
  await studio.selectOption("#app-accent", d.accent);
  steps.push("configure");
  say("the designer chooses the attributes a list shows and relabels a screen; what a person changed is marked",
      (await studio.locator("[data-testid=app-columns] input:checked").count()) === listView.columns.length - 1 &&
      (await studio.textContent("[data-testid=app-basis]")).includes("confirmed by a person"));
  const work = generated.views.find((v) => v.type === "WorkflowView");
  await studio.click(`tr[data-view=${work.id}] button.link`);
  await studio.waitForSelector("[data-testid=app-actions]");
  say("the designer shows each action with the rules that govern it, and offers no way to change them",
      (await studio.textContent("[data-testid=app-actions]")).includes("rules ") &&
      (await studio.locator("[data-testid=app-inspector] input, [data-testid=app-inspector] textarea").count()) === 0);
  await studio.click("[data-testid=app-preview-config]");
  await studio.waitForSelector("[data-testid=app-preview] [data-testid=rt-app]");
  steps.push("preview");
  say("the configuration preview is the application's own renderer, labelled, and reads no record",
      (await studio.getAttribute("[data-testid=app-preview] [data-testid=rt-app]", "data-mode")) === "configuration" &&
      (await studio.textContent("[data-testid=app-preview] [data-testid=rt-mode]")).includes("Configuration preview") &&
      (await studio.textContent("[data-testid=app-preview] [data-testid=rt-production]")).includes("unavailable") &&
      (await studio.locator("[data-testid=app-preview] [data-testid=rt-nav] > ul > li").count()) === generated.navigation.length &&
      (await studio.locator("[data-testid=app-preview] [data-testid=rt-no-data]").count()) >= 1);
  await studio.click("[data-testid=app-preview-config]");
  await studio.click("[data-testid=app-validate]");
  await studio.waitForSelector("[data-testid=app-validation]");
  steps.push("validate");
  await studio.fill("#app-note", "e2e: first design");
  await studio.click("[data-testid=app-save]");
  await studio.waitForFunction(() => document.querySelector("[data-testid=app-message]")?.textContent.includes("Saved as design revision 1"));
  steps.push("save");
  say("the design is validated by the engine and saved as a versioned draft that runs nothing",
      (await studio.textContent("[data-testid=app-message]")).includes("not part of a governed release") &&
      (await studio.locator("[data-testid=app-history] li").count()) === 1 &&
      (await studio.textContent("[data-testid=app-cannot]")).includes("owner decision D24"));
  const designed = await states(studio, "app-governance");
  say("the designer says what the saved design is in the engine's six states: a validated draft bound to what runs, not a release artifact, not for production",
      same(designed, AS_DESIGNED) && (await studio.textContent("[data-testid=app-governance-summary]")).includes("not an approved release artifact") &&
      (await studio.textContent("[data-testid=app-governance] li[data-state=approved_release_artifact]")).includes("owner decision D34"), JSON.stringify(designed));
  await studio.screenshot({ path: `${OUT}/app-${ws}-designer.png`, fullPage: true });

  // ---- the application, at its own address, as the person who does the work
  await app.click("text=Ask again");
  await app.waitForSelector("[data-testid=rt-app]");
  const bar = await app.textContent(".rt-bar");
  say("the application says which solution it renders, that its data is synthetic and that production is unavailable",
      (await app.textContent("[data-testid=rt-title]")) === `${generated.title} desk` && bar.includes("Engine-backed simulation") &&
      (await app.getAttribute("[data-testid=rt-app]", "data-accent")) === d.accent &&
      bar.includes("synthetic records") && bar.includes("Production: unavailable") && bar.includes(generated.binding.model) &&
      bar.includes(generated.binding.configuration.slice(0, 12)) && bar.includes("stage simulation") && bar.includes("starts work"));
  const shown = await states(app, "rt-status");
  say("the application tells its user the same six states, and calls itself neither a release nor a production system",
      same(shown, AS_DESIGNED) && (await app.textContent("[data-testid=rt-status-summary]")).includes("design draft, validated, bound to the configuration that runs; not an approved release artifact; production not authorised"),
      JSON.stringify(shown));
  const nav = await app.textContent("[data-testid=rt-nav]");
  say("navigation is generated from the design, and a kind of record this person can never see is not in it",
      nav.includes(`${words(d.root)} (all)`) && nav.includes("Audit trail") && (d.hiddenLabel ? !nav.includes(d.hiddenLabel) : true) &&
      (await app.textContent("[data-testid=rt-cannot]")).includes("cannot do"));
  await app.waitForSelector(`[data-testid=rt-tile-${d.root}] .rt-big`);
  await app.waitForFunction((e) => /\d/.test(document.querySelector(`[data-testid=rt-tile-${e}] .rt-big`)?.textContent ?? ""), d.root);
  say("the overview counts the records shown to this person", (await app.textContent(`[data-testid=rt-tile-${d.root}] .rt-big`)).trim() === String(d.roots));
  await app.click(`[data-testid=rt-nav] button:has-text('${words(d.root)} (all)')`);
  await app.waitForSelector("[data-testid=rt-table] tbody tr");
  const head = await app.textContent("[data-testid=rt-table] thead");
  say("the list shows the authorised records with the columns the designer kept, a page at a time",
      (await app.locator("[data-testid=rt-table] tbody tr").count()) === d.roots && !head.includes(dropped.label) &&
      (await app.textContent("[data-testid=rt-count]")) === `1–${d.roots} of ${d.roots}`, head.slice(0, 80));
  await app.fill("#rt-filter", d.alone);
  say("filtering applies to the records loaded, and says so", (await app.locator("[data-testid=rt-table] tbody tr").count()) === 1 &&
      (await app.textContent("label[for=rt-filter]")).includes("loaded"));
  await app.fill("#rt-filter", "zz-no-such");
  say("an empty result is said plainly", (await app.textContent("[data-testid=rt-empty]")).includes("No loaded record"));
  await app.fill("#rt-filter", "");
  await app.screenshot({ path: `${OUT}/app-${ws}-list.png`, fullPage: true });
  await app.click(`[data-testid=rt-table] button:has-text('${d.waits}')`);
  await app.waitForSelector("[data-testid=rt-fields]");
  say("a record shows its fields and its recorded links",
      (await app.locator("[data-testid=rt-fields] div").count()) > 3 && (await app.locator(".rt-related").count()) > 0 &&
      (await app.textContent("[data-testid=rt-detail]")).includes("none is computed or inferred"));
  await app.screenshot({ path: `${OUT}/app-${ws}-record.png`, fullPage: true });
  await app.click("[data-testid=rt-open-links]");
  await app.waitForSelector("[data-testid=rt-graph] .rt-node");
  await app.waitForFunction(() => document.querySelectorAll("[data-testid=rt-link-table] tbody tr").length > 0);
  say("relationships are drawn from recorded links only, with the state of each linked record and a caution",
      (await app.locator("[data-testid=rt-graph] .rt-node").count()) >= 2 &&
      (await app.locator("[data-testid=rt-graph] .rt-edge").count()) === (await app.locator("[data-testid=rt-link-table] tbody tr").count()) &&
      (await app.textContent("[data-testid=rt-links-caution]")).includes("not a finding about anybody"));
  await app.screenshot({ path: `${OUT}/app-${ws}-relationships.png`, fullPage: true });

  // ---- governed work: the engine decides
  await app.click(`[data-testid=rt-nav] button:has-text('work')`);
  await app.waitForSelector("[data-testid=rt-actions] tbody tr");
  const rules = await app.textContent("[data-testid=rt-actions]");
  say("the workflow screen explains, from the model's rules, what a person decides and what is prohibited",
      rules.includes("a person decides") && rules.includes("prohibited when") && (await app.locator("[data-testid=rt-states] li").count()) > 2);
  const ask = async (record) => {
    await app.selectOption("#rt-work-record", record);
    await app.click("[data-testid=rt-start]");
    await app.waitForFunction((r) => document.querySelector("[data-testid=rt-run]")?.textContent.includes(`record ${r}`), record);
  };
  await ask(d.alone);
  say("where the policy allows it the work is done, on simulated tools, and the screen says nothing else was touched",
      (await app.textContent("[data-testid=rt-run-status]")) === "Completed" &&
      (await app.textContent("[data-testid=rt-run-simulated]")).includes("no other system was contacted") &&
      (await app.locator("[data-testid=rt-run-steps] li").count()) >= 2);
  await ask(d.refused);
  const refused = await app.textContent("[data-testid=rt-run-outcome]");
  say("a prohibited action is shown as refused by policy, with the engine's reason, and nothing was done",
      refused.startsWith("Refused by policy:") && refused.includes("prohibited") && (await app.locator("[data-testid=rt-run-steps] li").count()) === 0, refused.slice(0, 110));
  await app.screenshot({ path: `${OUT}/app-${ws}-refused.png`, fullPage: true });
  await ask(d.waits);
  say("an action the rules reserve waits for a person, and the requester is told they cannot decide it",
      (await app.textContent("[data-testid=rt-run-status]")) === "Waiting for a person's decision" &&
      (await app.textContent("[data-testid=rt-run-waits]")).includes("cannot decide a request you made"));
  await app.click(`[data-testid=rt-nav] button:has-text('Decisions waiting')`);
  await app.waitForSelector("[data-testid=rt-inbox-unavailable]");
  say("the decision inbox is not usable by someone the engine gives no review permission",
      (await app.textContent("[data-testid=rt-inbox-unavailable]")).includes("'review' permission") && (await app.locator("[data-testid=rt-approve]").count()) === 0);

  // ---- a form is a preview: nothing is stored
  await app.click(`[data-testid=rt-nav] button:has-text('${words(d.root)} (all)')`);
  await app.click("[data-testid=rt-new]");
  await app.waitForSelector("[data-testid=rt-form]");
  await app.fill("#rt-form-id", "NEW-E2E-1");
  await app.click("[data-testid=rt-form-submit]");
  await app.waitForSelector("[data-testid=rt-form-result]");
  const stored = await as(d.operator, "GET", `${ENG}/objects/NEW-E2E-1`);
  const direct = await as(d.operator, "POST", `${ENG}/objects`, { type: d.root, id: "NEW-E2E-2", attributes: {} });
  say("a form says it is a preview, nothing is saved, and the engine refuses the same write sent directly",
      (await app.textContent("[data-testid=rt-form-mode]")).includes("Preview only") &&
      (await app.textContent("[data-testid=rt-form-result]")).includes("Not saved") && stored.status === 404 && direct.status === 403,
      `read ${stored.status}, direct write ${direct.status}`);

  // ---- the person the rules name decides, in her own session
  const rev = await page();
  await rev.goto(`${STUDIO}/run/${ws}/${d.uc}`);
  await rev.fill("#rt-token", token(d.reviewer));
  await rev.click("form button[type=submit]");
  await rev.waitForSelector("[data-testid=rt-app]");
  await rev.click(`[data-testid=rt-nav] button:has-text('Decisions waiting')`);
  await rev.waitForSelector("[data-testid=rt-review]");
  const request = await rev.textContent("[data-testid=rt-review]");
  await rev.fill("[data-testid=rt-review] input", "e2e: checked");
  await rev.click("[data-testid=rt-approve]");
  await rev.waitForSelector("[data-testid=rt-inbox-message]");
  say("the reviewer sees the request with its rule, decides, and the engine records it and finishes the work",
      request.includes(d.waits) && request.includes("Rules:") && (await rev.textContent("[data-testid=rt-inbox-message]")).includes("approved") &&
      (await rev.textContent("[data-testid=rt-inbox-message]")).includes("Completed") && (await rev.textContent("[data-testid=rt-you]")).includes("decides reviews"));
  await rev.click(`[data-testid=rt-nav] button:has-text('Audit trail')`);
  say("a person without the audit permission is told the engine does not show her audit trails",
      (await rev.textContent("[data-testid=rt-audit-unavailable]")).includes("'audit' permission"));
  await rev.close();

  // ---- audit: the engine's record, and what is only this screen's
  await app.click(`[data-testid=rt-nav] button:has-text('Audit trail')`);
  await app.waitForSelector("#rt-audit-run option:nth-child(2)", { state: "attached" });
  const option = await app.locator("#rt-audit-run option", { hasText: d.waits }).first().getAttribute("value");
  await app.selectOption("#rt-audit-run", option);
  await app.waitForSelector("[data-testid=rt-audit-engine] li");
  const trail = await app.textContent("[data-testid=rt-audit-engine]");
  const mine = await app.textContent("[data-testid=rt-audit-interface]");
  say("the audit screen reads the engine's signed chain, with the person's decision in it, and keeps it apart from interface activity",
      (await app.textContent("[data-testid=rt-audit-verified]")) === "signed chain verifies" && trail.includes("A person decided") &&
      trail.includes(`approved by ${d.reviewer}`) && trail.includes("Policy check") && mine.includes("not an audit record") &&
      (await app.locator("[data-testid=rt-audit-interface] li").count()) >= 4);
  await app.screenshot({ path: `${OUT}/app-${ws}-audit.png`, fullPage: true });

  // ---- what only some data shows (the table says which lists to read, and what must be in them)
  for (const [entity, expected] of d.lists ?? []) {
    await app.click(`[data-testid=rt-nav] button:text-is('${words(entity)}')`);
    await app.waitForFunction((title) => document.querySelector("#rt-list-title")?.textContent === title
      && document.querySelectorAll("[data-testid=rt-table] tbody tr").length > 0, words(entity));
    const body = await app.textContent("[data-testid=rt-table]");
    say(`the ${words(entity).toLowerCase()} list shows, as recorded: ${expected.join(", ")}`, expected.every((x) => body.includes(x)));
  }

  // ---- keyboard, phone
  await app.focus("[data-testid=rt-nav] li:first-child button");
  await app.keyboard.press("Enter");
  await app.waitForSelector("[data-testid=rt-dashboard]");
  await app.setViewportSize({ width: 390, height: 844 });
  say("the application is reachable by keyboard and has no horizontal page scroll on a phone",
      (await app.locator("[data-testid=rt-dashboard]").count()) === 1 && (await noScroll(app)));
  await app.setViewportSize({ width: 1280, height: 900 });
  steps.push("run");
  return { steps, app, studio, as, d, ENG, UC, say, token, shape: generated.views.map((v) => v.type).sort().join() };
}

try {
  const runs = {};
  for (const ws of Object.keys(APPS)) runs[ws] = await demo(ws);
  check("the same designer and the same renderer produced three different applications, through the same steps",
        new Set(Object.values(runs).map((r) => r.steps.join())).size === 1 && new Set(Object.values(runs).map((r) => r.shape)).size === 3,
        runs.crisis.steps.join(" → "));

  // ---- security, as a browser sees it
  const n = runs.netintel;
  const anonymous = await n.as(null, "GET", `${n.ENG}/application`);
  const foreign = await n.as("crisis-omar", "GET", `${n.ENG}/application`);
  const accounts = await n.as(n.d.operator, "GET", `${n.ENG}/objects?type=BankAccount`);
  const hostile = (await n.as(n.d.admin, "GET", `${n.ENG}/application/draft`)).body;
  hostile.manifest.title = "<img src=x onerror=alert(1)>";
  const injected = await n.as(n.d.admin, "POST", `${n.ENG}/application/draft`, { manifest: hostile.manifest, expected_revision: hostile.revision, note: "x" });
  hostile.manifest.title = "ok"; hostile.manifest.views[0].script = "alert(1)";
  const extra = await n.as(n.d.admin, "POST", `${n.ENG}/application/draft`, { manifest: hostile.manifest, expected_revision: hostile.revision, note: "x" });
  check("nobody anonymous and nobody of another workspace reads an application; restricted records stay uncounted; hostile designs are refused",
        anonymous.status === 401 && [403, 404].includes(foreign.status) && accounts.body.total === 0 && accounts.body.items.length === 0 &&
        injected.status === 400 && extra.status === 400, `${anonymous.status} ${foreign.status} ${injected.status} ${extra.status}`);

  // ---- a list longer than a page
  const v = runs.venues;
  await v.app.click("[data-testid=rt-nav] button:text-is('Organiser')");
  await v.app.waitForFunction(() => document.querySelector("#rt-list-title")?.textContent === "Organiser" &&
    document.querySelectorAll("[data-testid=rt-table] tbody tr").length === 25);
  const firstPage = await v.app.textContent("[data-testid=rt-count]");
  await v.app.click(".rt-pager button:has-text('Next')");
  await v.app.waitForFunction(() => document.querySelector("[data-testid=rt-count]")?.textContent.startsWith("26–50"));
  await v.app.click(".rt-pager button:has-text('Next')");
  await v.app.waitForFunction(() => document.querySelector("[data-testid=rt-count]")?.textContent.startsWith("51–61"));
  check("venues: a list of 61 records is read a page at a time, and the last page says where it ends",
        firstPage === "1–25 of 61" && (await v.app.locator("[data-testid=rt-table] tbody tr").count()) === 11 &&
        (await v.app.isDisabled(".rt-pager button:has-text('Next')")) && (await noScroll(v.app)), firstPage);

  // ---- release binding: a new release is activated under a running application
  const pinned = v.d ? (await v.as(v.d.operator, "GET", `${v.ENG}/application`)).body.running.configuration : "";
  const draft = (await v.as(v.d.admin, "GET", `${v.ENG}/model/draft`)).body;
  draft.document.entities.Room.states.push("under_maintenance");
  const saved = await v.as(v.d.admin, "POST", `${v.ENG}/model/draft`, { document: draft.document, expected_revision: draft.revision, note: "e2e: a new state" });
  await v.as(v.d.approver, "POST", `${v.UC}/publish-draft`, { revision: saved.body.revision, reason: "e2e" });
  const rel = await v.as(v.d.admin, "POST", `${v.UC}/releases`, { note: "e2e: second release" });
  await v.as(v.d.approver, "POST", `${v.UC}/releases/${rel.body.number}/approve`, { reason: "e2e" });
  const activated = await v.as(v.d.admin, "POST", `${v.UC}/releases/${rel.body.number}/activate`, { reason: "e2e" });
  const stalePin = await v.as(v.d.operator, "GET", `${v.ENG}/objects?type=Room`, undefined, { "X-Autology-Configuration": pinned });
  await v.app.click("[data-testid=rt-nav] li:nth-child(3) button");
  await v.app.waitForSelector(".rt-main .error");
  const inPlace = await v.app.textContent(".rt-main .error");
  await v.app.click("[data-testid=rt-reload]");
  await v.app.waitForSelector("[data-testid=rt-refused]");
  check("after a new release the engine refuses the application's pinned requests, and the application shows nothing until it is designed again",
        activated.status === 200 && stalePin.status === 409 && inPlace.includes("another configuration") &&
        (await v.app.textContent("[data-testid=rt-refusal]")).includes("another configuration") &&
        (await v.app.textContent("[data-testid=rt-refusal-detail]")).includes(pinned.slice(0, 12)), `${activated.status} ${stalePin.status}`);
  await v.app.screenshot({ path: `${OUT}/app-venues-release-mismatch.png`, fullPage: true });
  await v.studio.reload();
  await v.studio.waitForSelector(`.uc-list button:has-text('${v.d.name}')`);
  await v.studio.click(`.uc-list button:has-text('${v.d.name}')`);
  await v.studio.click("role=tab[name='Application']");
  await v.studio.waitForSelector("[data-testid=app-stale]");
  const afterRelease = await states(v.studio, "app-governance");
  check("after a new release the same saved design is reported as a draft that is valid for nothing that runs and not ready for simulation",
        same(afterRelease, { ...AS_DESIGNED, validated_design: "no", configuration_bound: "no", simulation_ready: "no" }) &&
        (await v.studio.textContent("[data-testid=app-governance-summary]")).includes("saved for another configuration"), JSON.stringify(afterRelease));
  await v.studio.click("[data-testid=app-generate]");
  await v.studio.waitForFunction(() => document.querySelector("[data-testid=app-validation]")?.textContent.includes("accepts"));
  await v.studio.click("[data-testid=app-save]");
  await v.studio.waitForFunction(() => document.querySelector("[data-testid=app-message]")?.textContent.includes("Saved as design revision 2"));
  await v.app.click("text=Ask again");
  await v.app.waitForSelector("[data-testid=rt-app]");
  check("the designer is told the saved design is for another configuration; designed again for what runs, the application is shown again",
        (await v.app.textContent("[data-testid=rt-release]")).includes("design revision 2"));
  check("no page errors", errors.length === 0, errors.join("; ").slice(0, 300));
} catch (e) {
  check("the demonstration ran to its end", false, String(e).slice(0, 500));
} finally {
  await browser.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`${results.length - failed}/${results.length} application checks passed`);
process.exit(failed ? 1 : 0);
