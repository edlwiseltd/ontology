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
  await page.click("role=tab[name='Model']");
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
  await page.close();

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
    const move = await fetch("/platform/workspaces/acme/use-cases/claims/stage", { method: "POST", headers: h, body: JSON.stringify({ to: "pilot", reason: "bypass" }) });
    const foreign = await fetch("/platform/workspaces/northwind/use-cases", { headers: h });
    const other = await fetch("/w/northwind/u/claims/api/objects", { headers: h });
    return [move.status, foreign.status, other.status];
  });
  check("direct API calls are refused by the platform (403, 404, 404)", JSON.stringify(direct) === "[403,404,404]", JSON.stringify(direct));
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
