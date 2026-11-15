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
  await ada.waitForSelector("[data-testid=publish-needs-another]");
  const own = await ada.evaluate(async () => {  // ada saved the revision: the platform refuses her, whatever the UI shows
    const h = { Authorization: "Bearer " + sessionStorage.getItem("autology-studio-token"), "Content-Type": "application/json" };
    return (await fetch("/platform/v1/workspaces/acme/use-cases/water-ops/publish-draft", { method: "POST", headers: h,
      body: JSON.stringify({ revision: 2, reason: "bypass" }) })).status;
  });
  check("the author of a draft cannot publish it herself (403)",
        own === 403 && await ada.locator("button:has-text('Publish draft revision')").isDisabled(), String(own));
  const second = await browser.newPage();
  await second.goto(STUDIO);
  const published = await second.evaluate(async () => (await fetch("/platform/v1/workspaces/acme/use-cases/water-ops/publish-draft", {
    method: "POST", headers: { Authorization: "Bearer acme-maria", "Content-Type": "application/json" },
    body: JSON.stringify({ revision: 2, reason: "e2e: reviewed the designed model" }) })).status);
  await second.close();
  check("another person with release authority publishes it", published === 200, String(published));
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

  // 2b. access administration (increment D): tenant, members, grants, approvals, tokens. Studio asks; the platform
  //     decides, and the same routes called directly are refused whatever a screen shows.
  async function openAccess(token) {
    const p = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    p.on("pageerror", (e) => errors.push(String(e)));
    await p.goto(STUDIO);
    await p.fill("#token", token);
    await p.click("form button[type=submit]");
    await p.waitForSelector("[data-testid=open-access]");
    await p.click("[data-testid=open-access]");
    await p.waitForSelector("#acc-title");
    return p;
  }
  const call = (p, method, path, body) => p.evaluate(async ([m, u, b]) => {
    const h = { Authorization: "Bearer " + sessionStorage.getItem("autology-studio-token"), "Content-Type": "application/json" };
    return (await fetch(u, { method: m, headers: h, body: b ? JSON.stringify(b) : undefined })).status;
  }, [method, path, body]);
  const WSP = "/platform/v1/workspaces/acme";
  const adm = await openAccess("acme-ada");
  await adm.waitForSelector("table[aria-label=Members]");
  const ctxText = await adm.textContent("[data-testid=access-context]");
  check("access: tenant and workspace are named explicitly", ctxText.includes("Tenant") && ctxText.includes("Acme Insurance") && ctxText.includes("(acme)"), ctxText.trim().slice(0, 90));
  const adaRow = await adm.textContent("tr[data-member=ada]");
  check("access: an administrator's effective access is administration only", adaRow.includes("workspace administrator") && adaRow.includes("administration only, no business data"));
  check("access: members and their effective permissions are listed", (await adm.textContent("tr[data-member=hana]")).includes("data within row and field rules"));
  const unlabeled = await adm.evaluate(() => [...document.querySelectorAll(".access input, .access select")].filter((el) => !el.labels || el.labels.length === 0).length);
  check("access: every field has a label", unlabeled === 0, String(unlabeled));
  await adm.fill("#m-name", "e2e-zoe");
  await adm.fill("#m-why", "e2e: joins the claims team");
  await adm.click("text=Add member");
  await adm.waitForSelector("[data-testid=token-value]");
  const zoeToken = (await adm.textContent("[data-testid=token-value]")).trim();
  check("access: a member is added and the token is shown once", zoeToken.startsWith("atl_") && (await adm.textContent("tr[data-member=e2e-zoe]")).includes("no access"));
  await adm.click("text=I have copied it");
  check("access: the token is not kept on screen or in the history", !(await adm.content()).includes(zoeToken));
  await adm.selectOption("#g-member", "e2e-zoe");
  await adm.selectOption("#g-uc", "claims");
  await adm.fill("#g-roles", "claims_handler");
  await adm.fill("#g-why", "e2e: handles claims");
  await adm.click("text=Request grant");
  await adm.waitForSelector("[data-testid=approval-required]");
  await adm.waitForSelector("[data-pending]");
  const pendingId = await adm.getAttribute("[data-pending]", "data-pending");
  check("access: a grant request needs approval, and its proposer is offered none",
        (await adm.textContent("[data-testid=approval-required]")).includes("another person") &&
        (await adm.locator("[data-pending] button:has-text('Approve')").count()) === 0 &&
        (await adm.textContent("[data-testid=approval-hint]")).includes("you proposed it"));
  const ownApproval = await call(adm, "POST", `${WSP}/grants/${pendingId}/approve`, { reason: "bypass" });
  check("access: the proposer's direct approval is refused by the platform (403)", ownApproval === 403, String(ownApproval));
  const approver = await openAccess("acme-maria");
  await approver.waitForSelector("[data-pending]");
  await approver.fill("#acc-reason", "e2e: confirmed with the team lead");
  await approver.click("[data-pending] button:has-text('Approve')");
  await approver.waitForSelector("[data-testid=access-message]");
  await approver.waitForFunction(() => document.querySelector("tr[data-member=e2e-zoe]")?.textContent.includes("row and field rules"));
  check("access: an approver approves, and the member's effective access changes", (await approver.textContent("tr[data-member=e2e-zoe]")).includes("read"));
  check("access: an approver who is not an administrator is offered no member form", (await approver.locator("#m-name").count()) === 0);
  const approverAdds = await call(approver, "POST", `${WSP}/members`, { name: "x", reason: "bypass" });
  check("access: and the platform refuses her the call itself (403)", approverAdds === 403, String(approverAdds));
  // the new member signs in: she sees her use case, and the access screen tells her clearly that it is not hers
  const zoe = await openAccess(zoeToken);
  await zoe.waitForSelector("[data-testid=access-denied]");
  check("access: a member without authority gets a clear permission-denied state", (await zoe.textContent("[data-testid=access-denied]")).includes("do not have permission"));
  check("access: she still sees her own use case", (await zoe.locator(".uc-list button:has-text('Motor claims')").count()) === 1);
  const zoeCalls = await Promise.all([call(zoe, "GET", `${WSP}/members`), call(zoe, "GET", `${WSP}/access-review`),
    call(zoe, "POST", `${WSP}/members`, { name: "y", reason: "bypass" }),
    call(zoe, "POST", `${WSP}/grants`, { member: "e2e-zoe", use_case: "orders", permissions: ["read"], reason: "bypass" }),
    call(zoe, "POST", `${WSP}/members/hana/revoke`, { use_case: "claims", reason: "bypass" }),
    call(zoe, "GET", "/platform/v1/workspaces/northwind/members"), call(zoe, "GET", "/platform/v1/tenants/northwind")]);
  check("access: her direct calls are refused by the platform (403 ×5, then 404 for another tenant)", JSON.stringify(zoeCalls) === "[403,403,403,403,403,404,404]", JSON.stringify(zoeCalls));
  // unrestricted access is never given by accident
  await adm.click("[data-testid=open-access]");
  await adm.selectOption("#g-member", "e2e-zoe");
  await adm.check("fieldset label:has-text('admin (unrestricted') input");
  await adm.waitForSelector("[data-testid=unrestricted-ack]");
  await adm.fill("#g-why", "e2e: too much");
  await adm.click("text=Request grant");
  await adm.waitForSelector("[data-testid=access-error]");
  check("access: an unrestricted grant without acknowledgement is refused by the platform", (await adm.textContent("[data-testid=access-error]")).includes("unrestricted"));
  await adm.uncheck("fieldset label:has-text('admin (unrestricted') input");
  // a new token for a member who holds business data takes two people
  await adm.fill("#acc-reason", "e2e: laptop lost");
  await adm.click("tr[data-member=ivan] button:has-text('New token')");
  await adm.waitForSelector("[data-testid=approval-required]");
  check("access: re-keying a member with data needs a second person; the requester sees no token",
        (await adm.textContent("[data-testid=approval-required]")).includes("another person with authority") &&
        (await adm.locator("[data-testid=token-value]").count()) === 0);
  await approver.click("[data-testid=open-access]");
  await approver.reload();
  await approver.waitForSelector("[data-testid=open-access]");
  await approver.click("[data-testid=open-access]");
  await approver.waitForSelector("button:has-text('Issue the token')");
  await approver.fill("#acc-reason", "e2e: ivan confirmed by phone");
  await approver.click("button:has-text('Issue the token')");
  await approver.waitForSelector("[data-testid=token-value]");
  check("access: the second person issues the token and is the only one to see it", (await approver.textContent("[data-testid=issued-token]")).includes("ivan"));
  // revoking and removing take effect at once, and are in the history
  await adm.click("[data-testid=open-access]");
  await adm.fill("#acc-reason", "e2e: wrong team");
  await adm.click("tr[data-member=e2e-zoe] button:has-text('Revoke access')");
  await adm.waitForFunction(() => document.querySelector("tr[data-member=e2e-zoe]")?.textContent.includes("no access"));
  const afterRevoke = await call(zoe, "GET", "/w/acme/u/claims/api/v1/me");
  check("access: a revoked grant stops working at once", afterRevoke === 404, String(afterRevoke));
  await adm.fill("#acc-reason", "e2e: left the company");
  await adm.click("tr[data-member=e2e-zoe] button:has-text('Remove')");
  await adm.waitForFunction(() => !document.querySelector("tr[data-member=e2e-zoe]"));
  const afterRemoval = await call(zoe, "GET", "/platform/v1/me");
  const history = await adm.textContent("ol[aria-label='Administration history']");
  check("access: a removed member's token is refused (401) and every step is in the history",
        afterRemoval === 401 && ["member added", "grant proposed", "grant approved", "grant revoked", "member removed", "token requested"].every((e) => history.includes(e)),
        String(afterRemoval));
  check("access: the review states what waits for a person", /\d+ data grants/.test(await adm.textContent("[data-testid=review-summary]")));
  await adm.screenshot({ path: `${OUT}/desktop-access.png`, fullPage: true });
  // a person replaces her own token; Studio goes on with the new one, the old one is dead
  await approver.click("[data-testid=replace-my-token]");
  await approver.waitForSelector("[data-testid=token-value]");
  await approver.waitForFunction(() => sessionStorage.getItem("autology-studio-token") !== "acme-maria");
  const oldToken = await approver.evaluate(async () => (await fetch("/platform/v1/me", { headers: { Authorization: "Bearer acme-maria" } })).status);
  const newToken = await call(approver, "GET", "/platform/v1/me");
  check("access: replacing one's own token ends the old one and Studio continues with the new one", oldToken === 401 && newToken === 200, `${oldToken}, ${newToken}`);
  check("no page errors (access)", errors.length === 0, errors.join("; "));
  await zoe.close(); await approver.close(); await adm.close();

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
  await mobile.click("[data-testid=open-access]");
  await mobile.waitForSelector("table[aria-label=Members]");
  const overflowAccess = await mobile.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  check("mobile: the access screen has no horizontal page scroll", !overflowAccess);
  await mobile.screenshot({ path: `${OUT}/mobile-access.png`, fullPage: true });
  await ctx.close();
} finally {
  await browser.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
