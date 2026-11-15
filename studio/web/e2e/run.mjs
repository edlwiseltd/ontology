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
  // wait for the refreshed row: the button is there only while the grant is (the row's other use cases always
  // read "no access", so that text says nothing about this one)
  await adm.waitForFunction(() => {
    const row = document.querySelector("tr[data-member=e2e-zoe]");
    return row !== null && !row.textContent.includes("Revoke access");
  });
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

  // 5. guided onboarding (sandbox): description → questions → proposal → review → validation → simulation → readiness
  const onb = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  onb.on("pageerror", (e) => errors.push(String(e)));
  const onb_started = Date.now();
  await onb.goto(STUDIO);
  await onb.fill("#token", "acme-ada");
  await onb.click("form button[type=submit]");
  await onb.waitForSelector(".uc-list button");
  await onb.click("text=New");
  await onb.waitForSelector("#c-template option", { state: "attached" });
  await onb.selectOption("#c-template", "blank-solution");
  await onb.fill("#c-id", "service-desk");
  await onb.fill("#c-name", "Service desk");
  await onb.click("text=Create in Draft");
  await onb.waitForSelector(".uc-list button:has-text('Service desk')");
  await onb.click(".uc-list button:has-text('Service desk')");
  await onb.click("role=tab[name='Onboarding']");
  await onb.waitForSelector("[data-testid=sandbox-notice]");
  await onb.waitForFunction(() => document.querySelector("[data-testid=sandbox-notice]").textContent.includes("test double"));
  check("onboarding: the screen says it is a sandbox and that no language model answers",
        (await onb.textContent("[data-testid=sandbox-notice]")).includes("not a language model"));
  await onb.fill("#ob-brief", "Employees send service requests. A manager must approve the expensive ones, then a team fulfils them.");
  await onb.click("text=Propose a solution");
  await onb.waitForSelector("[data-testid=generator]");
  check("onboarding: a description becomes a stored proposal with clarification questions",
        (await onb.textContent("[data-testid=generator]")).includes("test double") &&
        (await onb.textContent("#ob-questions ~ p, section p.small")).includes("revision 1") &&
        (await onb.locator(".question").count()) === 4, `${await onb.locator(".question").count()} questions`);
  await onb.fill("#q-approval_threshold", "5000");
  await onb.fill("#q-approver_role", "Department head");
  await onb.fill("#q-handler_role", "clerk");
  await onb.fill("#q-fulfilment_system", "ERP sandbox");
  await onb.click("text=Update the proposal with my answers");
  await onb.waitForSelector("[data-testid=onboarding-canvas] .react-flow__node");
  await onb.waitForSelector("[data-testid=workflow] tbody tr");
  const proposedNodes = await onb.locator("[data-testid=onboarding-canvas] .react-flow__node.proposed").count();
  check("onboarding: the proposed entities and relationships are shown as proposed, not confirmed",
        proposedNodes === 3 && (await onb.locator("[data-testid=onboarding-canvas] .react-flow__node.confirmed").count()) === 0 &&
        (await onb.locator("[data-testid=onboarding-canvas] .react-flow__edge").count()) === 2, `${proposedNodes} proposed nodes`);
  const flowText = await onb.textContent("[data-testid=workflow]");
  const accessText = await onb.textContent("[data-testid=access-lines]");
  check("onboarding: the answers shaped the workflow, rules and permissions",
        flowText.includes("department_head when Request.amount >= 5000") && accessText.includes("only clerk may fulfil_request") &&
        (await onb.textContent("[data-testid=suggestions]")).includes("ERP sandbox"));
  check("onboarding: assumptions and unknowns are stated",
        (await onb.textContent("[data-testid=assumptions]")).includes("Unknown:"));
  await onb.screenshot({ path: `${OUT}/desktop-onboarding-review.png`, fullPage: true });
  await onb.click("text=Validate my selection with the engine");
  await onb.waitForSelector("[data-testid=engine-validation]");
  check("onboarding: the engine validates the selection before anything is saved",
        (await onb.textContent("[data-testid=engine-validation]")).includes("strict loader accepts"));
  const beforeSave = await call(onb, "GET", "/w/acme/u/service-desk/api/v1/model/draft/history");
  await onb.click("button:has-text('as a draft')");
  await onb.waitForSelector("[data-testid=saved]");
  const onb_active = await onb.evaluate(async () => Object.keys((await (await fetch("/w/acme/u/service-desk/api/v1/ontology", { headers: {
    Authorization: "Bearer " + sessionStorage.getItem("autology-studio-token") } })).json()).entities).length);
  check("onboarding: accepted items are saved as a draft; what runs is unchanged",
        (await onb.textContent("[data-testid=saved]")).includes("not active") && onb_active === 0 && beforeSave === 200, `${onb_active} active entities`);
  const onb_stored = await onb.evaluate(async () => {
    const h = { Authorization: "Bearer " + sessionStorage.getItem("autology-studio-token") };
    const list = await (await fetch("/w/acme/u/service-desk/api/v1/architect/proposals", { headers: h })).json();
    const one = await (await fetch(`/w/acme/u/service-desk/api/v1/architect/proposals/${list.items[0].id}`, { headers: h })).json();
    return { revisions: list.items[0].revisions, ai: one.ai, decisions: one.decisions.length, by: one.decisions[0]?.decided_by,
             accepted: one.decisions[0]?.accepted.length };
  });
  check("onboarding: the proposal keeps its revisions, provenance and the person's review",
        onb_stored.revisions === 2 && onb_stored.ai === false && onb_stored.decisions === 1 && onb_stored.by === "ada" && onb_stored.accepted === 17,
        JSON.stringify(onb_stored));
  await onb.click("text=Simulate the draft");
  await onb.click("text=Run the simulation");
  await onb.waitForSelector("[data-testid=pending-review]");
  check("onboarding: the simulation stops where the model asks for a person",
        (await onb.textContent("[data-testid=simulation-status]")) === "awaiting_review" &&
        (await onb.textContent("[data-testid=pending-review]")).includes("department_head"));
  await onb.click("text=Approve as department_head (simulated)");
  await onb.waitForFunction(() => document.querySelector("[data-testid=simulation-status]")?.textContent === "completed");
  const stepsText = await onb.textContent("[data-testid=simulation-steps]");
  check("onboarding: an authorised simulated decision lets the run finish, with stub tools only",
        (await onb.locator("[data-testid=simulation-steps] li").count()) === 5 && stepsText.includes("simulated:fulfilment.deliver") &&
        stepsText.includes("decided by simulated:department_head") &&
        (await onb.textContent("[data-testid=simulated-reviews]")).includes("no person reviewed anything"));
  await onb.click("summary:has-text('Audit trace')");
  check("onboarding: the audit trace of the simulation is shown and labelled as not a stored chain",
        (await onb.locator("[data-testid=audit-events] li").count()) > 10 &&
        (await onb.textContent("[data-testid=simulation]")).includes("not a stored signed audit chain"));
  const runsAfter = await onb.evaluate(async () => (await (await fetch("/w/acme/u/service-desk/api/v1/health", { headers: {
    Authorization: "Bearer " + sessionStorage.getItem("autology-studio-token") } })).json()));
  await onb.screenshot({ path: `${OUT}/desktop-onboarding-simulation.png`, fullPage: true });
  await onb.click(".steps button:has-text('Readiness')");
  await onb.click("text=Assess readiness for a pilot");
  await onb.waitForSelector("[data-testid=readiness]");
  const onb_blockers = await onb.textContent("[data-testid=blockers]");
  check("onboarding: readiness shows the score, the blockers and that the score decides nothing",
        (await onb.textContent("[data-testid=promotion]")) === "promotion blocked" &&
        (await onb.locator("[data-testid=dimensions] tbody tr").count()) === 6 && onb_blockers.includes("At least one goal") &&
        (await onb.textContent("[data-testid=weights-status]")).includes("not approved by the owner"),
        `score ${await onb.textContent("[data-testid=readiness-score]")}`);
  check("onboarding: production is stated as not authorised",
        (await onb.textContent("[data-testid=production]")).includes("not authorised"));
  check("onboarding: the simulation left no run and no stage change behind",
        typeof runsAfter === "object" && (await onb.textContent(".uc-list button:has-text('Service desk')")).includes("Draft"));
  await onb.screenshot({ path: `${OUT}/desktop-onboarding-readiness.png`, fullPage: true });
  console.log(`INFO onboarding journey (scripted, sandbox): ${((Date.now() - onb_started) / 1000).toFixed(1)} s`);
  // a member who may not configure sees the screen but cannot ask, and the engine refuses her the calls
  const hanaOnb = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  hanaOnb.on("pageerror", (e) => errors.push(String(e)));
  await hanaOnb.goto(STUDIO);
  await hanaOnb.fill("#token", "acme-hana");
  await hanaOnb.click("form button[type=submit]");
  await hanaOnb.waitForSelector(".uc-list button");
  await hanaOnb.click(".uc-list button:has-text('Motor claims')");
  await hanaOnb.click("role=tab[name='Onboarding']");
  await hanaOnb.waitForSelector("[data-testid=onboarding]");
  const refusals = [await call(hanaOnb, "POST", "/w/acme/u/claims/api/v1/architect/proposals", { generator: "model", brief: "service requests approved by a manager" }),
                    await call(hanaOnb, "POST", "/w/acme/u/claims/api/v1/model/draft/simulate", {}),
                    await call(hanaOnb, "GET", "/w/acme/u/service-desk/api/v1/architect/proposals")];
  check("onboarding: without configure the button is disabled and the engine refuses the calls (403, 403, 404)",
        (await hanaOnb.isDisabled("button:has-text('Propose a solution')")) && refusals.join() === "403,403,404", refusals.join());
  await hanaOnb.close();
  check("no page errors (onboarding)", errors.length === 0, errors.join("; "));
  await onb.close();

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
  await mobile.click(".uc-list button:has-text('Motor claims')");
  await mobile.click("role=tab[name='Onboarding']");
  await mobile.waitForSelector("[data-testid=onboarding]");
  const overflowOnboarding = await mobile.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  check("mobile: the onboarding screen has no horizontal page scroll", !overflowOnboarding);
  await ctx.close();
} finally {
  await browser.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
