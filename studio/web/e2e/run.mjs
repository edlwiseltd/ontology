// Browser tests of Studio against a real platform (started by e2e/run.sh). Prints one line per check.
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw;
try { pw = require("playwright"); } catch { pw = require("/opt/node22/lib/node_modules/playwright"); }
const STUDIO = process.env.STUDIO_URL ?? "http://127.0.0.1:8961";
const OUT = process.env.SHOTS ?? "e2e/screenshots";
mkdirSync(OUT, { recursive: true });
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };

function luminance(rgb) {
  const [r, g, b] = rgb.match(/\d+/g).slice(0, 3).map(Number).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a, b) => { const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

const browser = await pw.chromium.launch();
try {
  // 1. desktop: the administrator's journey
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const res = await page.goto(STUDIO);
  check("CSP header present", /default-src 'self'/.test(res.headers()["content-security-policy"] ?? ""));
  await page.fill("#token", "acme-ada");
  await page.click("form button[type=submit]");
  await page.waitForSelector(".uc-list button");
  check("workspace and use cases from the real platform", (await page.textContent(".bar")).includes("Acme Insurance"));
  await page.click(".uc-list button:has-text('Motor claims')");
  await page.waitForSelector("[data-testid=execution]");
  check("draft use case: the engine runs nothing", (await page.textContent("[data-testid=execution]")).includes("Nothing runs"));
  await page.click("text=Check now");
  await page.waitForSelector(".checks li");
  await page.selectOption("#move-to", "simulation");
  await page.fill("#move-reason", "e2e: first simulation");
  await page.click("text=Record the move");
  await page.waitForSelector(".history li");
  check("stage moved through the platform and recorded", (await page.textContent(".history")).includes("e2e: first simulation"));
  await page.screenshot({ path: `${OUT}/desktop-overview.png` });
  const t0 = Date.now();
  await page.click("role=tab[name='Active model']");
  await page.waitForSelector(".react-flow__node");
  const ms = Date.now() - t0;
  const nodes = await page.locator(".react-flow__node").count();
  const listed = await page.locator(".entity-list button").count();
  check("canvas and list are views of one model", nodes === listed && nodes > 3, `${nodes} nodes, ${listed} list items, rendered in ${ms} ms`);
  await page.locator(".entity-list button").first().focus();
  await page.keyboard.press("Enter");
  await page.waitForSelector(".inspector table");
  check("keyboard selects an entity; inspector shows it", (await page.textContent(".inspector h3")).length > 0);
  await page.screenshot({ path: `${OUT}/desktop-model.png` });
  // dark theme contrast
  await page.selectOption("#theme", "dark");
  const [fg, bg] = await page.evaluate(() => { const s = getComputedStyle(document.body); return [s.color, s.backgroundColor]; });
  const ratio = contrast(fg, bg);
  check("dark theme text contrast ≥ 4.5:1", ratio >= 4.5, ratio.toFixed(1) + ":1");
  await page.screenshot({ path: `${OUT}/desktop-model-dark.png` });
  await page.selectOption("#theme", "light");
  const [fg2, bg2] = await page.evaluate(() => { const s = getComputedStyle(document.body); return [s.color, s.backgroundColor]; });
  check("light theme text contrast ≥ 4.5:1", contrast(fg2, bg2) >= 4.5, contrast(fg2, bg2).toFixed(1) + ":1");
  // create a use case from an operator-approved template: it starts in Draft
  await page.click("text=New");
  await page.waitForSelector("#c-template option", { state: "attached" });
  await page.fill("#c-id", "claims-e2e");
  await page.fill("#c-name", "Claims e2e");
  await page.click("text=Create in Draft");
  await page.waitForSelector(".uc-list button:has-text('Claims e2e')");
  check("use case created from a template starts in Draft",
        (await page.textContent(".uc-list button:has-text('Claims e2e')")).includes("Draft"));
  check("no page errors", errors.length === 0, errors.join("; "));

  // 4. increment 2: design a synthetic water-treatment model from a brief
  await page.click("text=New");
  await page.waitForSelector("#c-template option", { state: "attached" });
  await page.selectOption("#c-template", "industrial-starter");
  await page.fill("#c-id", "water-ops");
  await page.fill("#c-name", "Water operations");
  await page.click("text=Create in Draft");
  await page.waitForSelector(".uc-list button:has-text('Water operations')");
  await page.click(".uc-list button:has-text('Water operations')");
  await page.click("role=tab[name='Design (draft)']");
  await page.waitForSelector("[data-testid=validity]");
  check("design starts from the active model, valid", (await page.textContent("[data-testid=validity]")).includes("valid (engine)")
        && (await page.locator("[data-testid=design-canvas] .react-flow__node").count()) === 1);
  await page.fill("#brief", "We operate multiple treatment plants. Model our pump assets, maintenance process, technicians, supervisors and approval responsibilities.");
  await page.click("text=Propose");
  await page.waitForSelector(".provisional-item");
  const proposed = await page.locator(".provisional-item").count();
  check("brief gives provisional items labelled not AI", proposed >= 8 && (await page.textContent(".proposal")).includes("blueprint · not AI"),
        `${proposed} items`);
  const tAccept = Date.now();
  await page.click("text=Accept selected");
  await page.waitForFunction(() => document.querySelectorAll("[data-testid=design-canvas] .react-flow__node").length === 5);
  await page.waitForFunction(() => document.querySelector("[data-testid=validity]").textContent.startsWith("checking"));
  await page.waitForFunction(() => document.querySelector("[data-testid=validity]").textContent.startsWith("valid"));
  check("accepted items appear as new (dashed) nodes and the engine validates them",
        (await page.locator("[data-testid=design-canvas] .react-flow__node.provisional").count()) === 4, `${Date.now() - tAccept} ms to engine-validated`);
  check("questions come from real gaps", (await page.textContent(".questions")).includes("maintenance_supervisor"));
  await page.click("[data-testid=design-canvas] .react-flow__node[data-id='Pump']");
  await page.waitForSelector("[data-testid=entity-inspector]");
  await page.fill("#new-attr", "flow");
  await page.fill("#new-attr-type", "nmber");
  await page.click("[data-testid=entity-inspector] form button[type=submit]");
  await page.waitForFunction(() => document.querySelector("[data-testid=validity]").textContent.startsWith("invalid"), null, { timeout: 10000 });
  const problemText = await page.textContent("[data-testid=entity-inspector] .error");
  check("a malformed attribute is refused by the engine and anchored to its node",
        problemText.includes("did you mean 'number'") && (await page.locator(".react-flow__node.problem[data-id='Pump']").count()) === 1);
  await page.selectOption("#t-flow", "number");
  await page.waitForFunction(() => document.querySelector("[data-testid=validity]").textContent.startsWith("valid"));
  check("fixing it in the inspector makes the model valid again", true);
  await page.fill("#save-note", "e2e: water blueprint");
  await page.click("text=Save draft");
  await page.waitForFunction(() => document.querySelector(".design-bar strong").textContent.includes("revision 1"));
  check("draft saved as revision 1; nothing unsaved", (await page.textContent(".design-bar")).includes("saved"));
  await page.screenshot({ path: `${OUT}/desktop-design.png` });
  // someone else saves meanwhile: the next save is refused, not silently overwritten
  const other = await page.evaluate(async () => {
    const h = { Authorization: "Bearer " + sessionStorage.getItem("autology-studio-token"), "Content-Type": "application/json" };
    const d = await (await fetch("/w/acme/u/water-ops/api/v1/model/draft", { headers: h })).json();
    const r = await fetch("/w/acme/u/water-ops/api/v1/model/draft", { method: "POST", headers: h,
      body: JSON.stringify({ document: d.document, expected_revision: d.revision, note: "someone else" }) });
    return r.status;
  });
  await page.click("[data-testid=design-canvas] .react-flow__node[data-id='Plant']");
  await page.fill("#e-desc", "A treatment plant (edited)");
  await page.click("text=Save draft");
  await page.waitForSelector(".warn:has-text('Someone saved revision 2')");
  check("a stale save is refused (409) and the user is told", other === 200);
  check("the active model is unchanged by drafts",
        (await page.evaluate(async () => Object.keys((await (await fetch("/w/acme/u/water-ops/api/v1/ontology", { headers: {
          Authorization: "Bearer " + sessionStorage.getItem("autology-studio-token") } })).json()).entities))).join() === "Plant");
  check("no page errors (design)", errors.length === 0, errors.join("; "));
  await page.close();

  // 1b. releases (REL-1a, STU-6): ada proposes, maria (a named release approver) approves, ada activates
  async function signIn(token, uc) {
    const p = await browser.newPage({ viewport: { width: 1280, height: 860 } });
    p.on("pageerror", (e) => errors.push(String(e)));
    await p.goto(STUDIO);
    await p.fill("#token", token);
    await p.click("form button[type=submit]");
    await p.waitForSelector(".uc-list button");
    await p.click(`.uc-list button:has-text('${uc}')`);
    await p.waitForSelector("[data-testid=execution]");
    await p.click("[role=tab]:has-text('Releases')");
    await p.waitForSelector("#rel-title");
    return p;
  }
  const ada = await signIn("acme-ada", "Motor claims");
  await ada.fill("#rel-note", "e2e: the configured claims model");
  await ada.click("text=Propose release");
  await ada.waitForSelector(".releases tr[data-status=proposed]");
  check("a release is proposed from Studio", true);
  check("the proposer is offered no approval", (await ada.locator(".releases button:has-text('Approve')").count()) === 0);
  const maria = await signIn("acme-maria", "Motor claims");
  await maria.fill("#rel-reason", "e2e: reviewed the snapshot");
  await maria.click(".releases button:has-text('Approve')");
  await maria.waitForSelector(".releases tr[data-status=approved]");
  const asApprover = await maria.evaluate(async () => {
    const h = { Authorization: "Bearer " + sessionStorage.getItem("autology-studio-token"), "Content-Type": "application/json" };
    return (await fetch("/platform/v1/workspaces/acme/use-cases/claims/releases/1/activate", { method: "POST", headers: h,
      body: JSON.stringify({ reason: "bypass" }) })).status;
  });
  check("another person approves; an approver cannot activate (403)", asApprover === 403, String(asApprover));
  await ada.click("[role=tab]:has-text('Overview')");
  await ada.click("[role=tab]:has-text('Releases')");
  await ada.waitForSelector(".releases tr[data-status=approved]");
  await ada.fill("#rel-reason", "e2e: go");
  await ada.click(".releases button:has-text('Activate')");
  await ada.waitForSelector("[data-testid=active-release]");
  check("the administrator activates the approved release",
        (await ada.textContent("[data-testid=active-release]")).trim() === "1");
  await ada.screenshot({ path: `${OUT}/desktop-releases.png` });
  await maria.close();
  // publishing a saved draft makes it the use case's model (through the platform; nothing written to shared files)
  await ada.click(".uc-list button:has-text('Water')");  // the Releases tab stays selected
  await ada.waitForSelector("text=Publish draft revision");
  await ada.fill("#rel-reason", "e2e: publish the designed model");
  await ada.click("button:has-text('Publish draft revision')");
  await ada.waitForSelector(".ok:has-text('published')");
  const active = await ada.evaluate(async () => Object.keys((await (await fetch("/w/acme/u/water-ops/api/v1/ontology", {
    headers: { Authorization: "Bearer " + sessionStorage.getItem("autology-studio-token") } })).json()).entities).length);
  check("a published draft becomes the use case's active model", active > 1, `${active} entities`);
  check("no page errors (releases)", errors.length === 0, errors.join("; "));
  await ada.close();

  // 2. denial: a member who is not an administrator, and a direct API call that bypasses the UI
  const hana = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  await hana.goto(STUDIO);
  await hana.fill("#token", "acme-hana");
  await hana.click("form button[type=submit]");
  await hana.waitForSelector(".uc-list button");
  await hana.click(".uc-list button");
  await hana.waitForSelector("[data-testid=execution]");
  check("non-admin sees no stage form", (await hana.locator("#move-to").count()) === 0);
  const direct = await hana.evaluate(async () => {
    const h = { Authorization: "Bearer " + sessionStorage.getItem("autology-studio-token"), "Content-Type": "application/json" };
    const calls = (p, e) => [
      fetch(`/platform${p}/workspaces/acme/use-cases/claims/stage`, { method: "POST", headers: h, body: JSON.stringify({ to: "pilot", reason: "bypass" }) }),
      fetch(`/platform${p}/workspaces/northwind/use-cases`, { headers: h }),
      fetch(`/w/northwind/u/claims/api${e}/objects`, { headers: h }),
      fetch(`/w/acme/u/claims/api${e}/model/draft`, { method: "POST", headers: h, body: JSON.stringify({ document: {}, expected_revision: 0 }) }),
      fetch(`/w/acme/u/claims/api${e}/architect/proposals`, { method: "POST", headers: h, body: JSON.stringify({ brief: "pumps and plants" }) })];
    const v1 = await Promise.all(calls("/v1", "/v1"));
    const legacy = await Promise.all(calls("", ""));
    const body = await v1[0].json();
    return { v1: v1.map((r) => r.status), legacy: legacy.map((r) => r.status), envelope: body.error && body.error.status };
  });
  check("direct API v1 calls are refused by the platform (403, 404, 404, 403, 403)", JSON.stringify(direct.v1) === "[403,404,404,403,403]", JSON.stringify(direct.v1));
  check("the same direct calls on the legacy paths are refused too", JSON.stringify(direct.legacy) === "[403,404,404,403,403]", JSON.stringify(direct.legacy));
  check("v1 refusals use the error envelope", direct.envelope === 403);
  await hana.close();

  // 3. mobile
  const ctx = await browser.newContext({ ...pw.devices["iPhone 13"] });
  const mobile = await ctx.newPage();
  await mobile.goto(STUDIO);
  await mobile.fill("#token", "acme-ada");
  await mobile.click("form button[type=submit]");
  await mobile.waitForSelector(".uc-list button");
  await mobile.click(".uc-list button:has-text('Motor claims')");
  await mobile.waitForSelector("[data-testid=execution]");
  const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  check("mobile: no horizontal page scroll", !overflow);
  await mobile.screenshot({ path: `${OUT}/mobile-overview.png`, fullPage: true });
  await ctx.close();
} finally {
  await browser.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
