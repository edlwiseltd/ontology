// Capture the visual language of a reference web interface, so that a design system can follow what is really
// there instead of what someone remembers: screenshots at three sizes, the stylesheets, and an inventory of the
// colours, type, spacing and components the pages actually use.
//
//   node tools/capture_reference.mjs <address> --pages "First,Second,Third" [--scramble] [--out folder]
//
// A browser window opens. Sign in if the site asks, open each page when the terminal names it, and press Enter.
// Everything is written to a local folder. Nothing is sent anywhere: sharing the folder is the operator's choice.
//
//   --scramble   replace every letter and digit on screen before a screenshot (layout and type stay; text does not).
//                Images, charts and logos are not altered: look at the screenshots before sharing them.
//   --auto "Name=address;Name=address"   no questions: open each address and capture it (for pages with their own address)
//   --browser msedge|chrome|chromium     which browser to drive (default: the first of these that starts)
//   --headless                           no window (only useful with --auto)
//
// The inventory files hold no text of the pages: tag names, class names, measurements and style values only.
// The one exception is navigation.json, the labels of menus and tabs, written before any scrambling.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline/promises";
import { chromium } from "playwright";

const SIZES = { desktop: { width: 1440, height: 900 }, tablet: { width: 820, height: 1180 }, mobile: { width: 390, height: 844 } };
const args = process.argv.slice(2);
const flag = (name) => args.includes(`--${name}`);
const value = (name, fallback) => (args.includes(`--${name}`) ? args[args.indexOf(`--${name}`) + 1] : fallback);
const address = args.find((a) => /^https?:\/\//.test(a));
if (!address) {
  console.error('usage: node tools/capture_reference.mjs <address> --pages "First,Second" [--scramble] [--out folder]');
  process.exit(2);
}
const out = value("out", "reference-capture");
const auto = (value("auto", "") || "").split(";").filter(Boolean).map((p) => { const at = p.indexOf("="); return [p.slice(0, at), p.slice(at + 1)]; });
const named = (value("pages", "") || "").split(",").map((s) => s.trim()).filter(Boolean);
const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "page";
mkdirSync(join(out, "css"), { recursive: true });

async function start() {
  const order = value("browser") ? [value("browser")] : ["msedge", "chrome", "chromium"];
  for (const name of order) {
    try {
      return [await chromium.launch({ headless: flag("headless"), ...(name === "chromium" ? {} : { channel: name }) }), name];
    } catch { /* that browser is not installed: try the next */ }
  }
  throw new Error("no browser could be started: install Edge or Chrome, or run `npx playwright install chromium`");
}

// what a page uses, read in the page: values and names, never the text it shows
function inventory() {
  const KEYS = ["color", "backgroundColor", "fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "textTransform",
    "borderTopWidth", "borderTopStyle", "borderTopColor", "borderRadius", "boxShadow", "paddingTop", "paddingRight", "paddingBottom",
    "paddingLeft", "marginTop", "marginBottom", "gap", "display", "position", "height", "width", "textAlign"];
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
  const describe = (el) => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return { tag: el.tagName.toLowerCase(), classes: [...el.classList].slice(0, 12), role: el.getAttribute("role"), type: el.getAttribute("type"),
      box: { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) },
      style: Object.fromEntries(KEYS.map((k) => [k, s[k]])) };
  };
  const all = [...document.querySelectorAll("body *")].filter(visible).slice(0, 6000);
  const count = (pick) => { const m = new Map(); for (const el of all) { const v = pick(getComputedStyle(el), el); if (v) m.set(v, (m.get(v) || 0) + 1); } return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 40); };
  // custom properties as they are declared, per selector and per media condition (a dark theme is a second set, not an overwrite)
  const tokens = [];
  const read = (rules, media) => {
    for (const rule of rules || []) {
      if (rule.cssRules && rule.conditionText !== undefined) { read(rule.cssRules, rule.conditionText); continue; }
      if (!rule.style) continue;
      const found = {};
      for (const name of rule.style) if (name.startsWith("--")) found[name] = rule.style.getPropertyValue(name).trim();
      if (Object.keys(found).length) tokens.push({ selector: (rule.selectorText || "").slice(0, 200), media: media || null, properties: found });
    }
  };
  for (const sheet of document.styleSheets) { try { read(sheet.cssRules, null); } catch { /* a stylesheet of another origin cannot be read here: its file is saved instead */ } }
  const pick = (selector, limit = 6) => [...document.querySelectorAll(selector)].filter(visible).slice(0, limit).map(describe);
  const raised = all.filter((el) => { const s = getComputedStyle(el); const r = el.getBoundingClientRect(); return r.width > 120 && r.height > 60 && (s.boxShadow !== "none" || (parseFloat(s.borderTopWidth) > 0 && parseFloat(s.borderRadius) > 0)); }).slice(0, 14).map(describe);
  const outline = (el, depth) => ({ tag: el.tagName.toLowerCase(), classes: [...el.classList].slice(0, 6), role: el.getAttribute("role") || undefined,
    children: depth > 0 ? [...el.children].filter(visible).slice(0, 14).map((c) => outline(c, depth - 1)) : undefined });
  const labels = [...document.querySelectorAll("nav a, nav button, aside a, aside button, header a, header button, [role=navigation] a, [role=navigation] button, [role=tab], [role=menuitem], [role=menubar] *")]
    .filter(visible).map((el) => (el.textContent || "").replace(/\s+/g, " ").trim()).filter((t) => t && t.length <= 60);
  return {
    viewport: { width: innerWidth, height: innerHeight }, document: { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight },
    language: document.documentElement.lang || null, custom_properties: tokens, body: describe(document.body),
    used: { text_colours: count((s) => s.color), backgrounds: count((s) => (s.backgroundColor === "rgba(0, 0, 0, 0)" ? null : s.backgroundColor)),
      font_families: count((s) => s.fontFamily), font_sizes: count((s) => s.fontSize), font_weights: count((s) => s.fontWeight),
      radii: count((s) => (s.borderRadius === "0px" ? null : s.borderRadius)), shadows: count((s) => (s.boxShadow === "none" ? null : s.boxShadow)),
      border_colours: count((s) => (parseFloat(s.borderTopWidth) > 0 ? s.borderTopColor : null)), gaps: count((s) => (s.gap === "normal" ? null : s.gap)),
      paddings: count((s) => (s.paddingTop === "0px" && s.paddingLeft === "0px" ? null : `${s.paddingTop} ${s.paddingRight} ${s.paddingBottom} ${s.paddingLeft}`)) },
    components: { header: pick("header, [role=banner]", 2), navigation: pick("nav, aside, [role=navigation]", 4), navigation_items: pick("nav a, nav button, aside a, aside button, [role=tab], [role=menuitem]", 10),
      headings: pick("h1, h2, h3, h4", 10), buttons: pick("button, [role=button], input[type=submit]", 12), links: pick("main a, a", 6),
      fields: pick("input, select, textarea", 8), tables: pick("table", 3), table_headers: pick("th", 6), table_cells: pick("td", 8),
      badges: pick("[class*=badge], [class*=tag], [class*=chip], [class*=pill], [class*=status]", 10), raised_surfaces: raised,
      graphics: pick("svg, canvas", 6) },
    outline: outline(document.body, 6), navigation_labels: [...new Set(labels)].slice(0, 200),
  };
}

// every letter becomes x and every digit 0, so a screenshot shows layout and type and none of the content
function scramble() {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    node.nodeValue = node.nodeValue.replace(/\p{Lu}/gu, "X").replace(/\p{L}/gu, "x").replace(/\p{N}/gu, "0");
  }
  for (const field of document.querySelectorAll("input, textarea")) {
    if (field.value) field.value = field.value.replace(/\p{L}/gu, "x").replace(/\p{N}/gu, "0");
    if (field.placeholder) field.placeholder = field.placeholder.replace(/\p{L}/gu, "x");
  }
  for (const el of document.querySelectorAll("[title], [aria-label], [alt]")) for (const a of ["title", "aria-label", "alt"]) if (el.hasAttribute(a)) el.setAttribute(a, "x");
}

const sheets = new Map();
async function stylesheets(page) {
  const found = await page.evaluate(() => [...document.styleSheets].map((s, n) => ({ n, href: s.href, text: s.href ? null : (s.ownerNode && s.ownerNode.textContent) || "" })));
  for (const sheet of found) {
    const key = sheet.href || `inline:${sheet.text.length}:${sheet.text.slice(0, 80)}`;
    if (sheets.has(key)) continue;
    let text = sheet.text;
    if (sheet.href) { try { text = await (await page.request.get(sheet.href)).text(); } catch { text = null; } }
    if (text === null || !text.trim()) continue;
    const name = `${String(sheets.size + 1).padStart(2, "0")}-${sheet.href ? slug(new URL(sheet.href).pathname.split("/").pop() || "sheet") : "inline"}.css`;
    sheets.set(key, name);
    writeFileSync(join(out, "css", name), text.slice(0, 5_000_000));
  }
}

async function capture(page, name) {
  const id = slug(name);
  await page.setViewportSize(SIZES.desktop);
  await page.waitForTimeout(700);
  await stylesheets(page);
  const where = new URL(page.url());
  const record = { page: name, path: where.pathname + where.hash.split("?")[0], sizes: {} };
  for (const [size, viewport] of Object.entries(SIZES)) {
    await page.setViewportSize(viewport);
    await page.waitForTimeout(700);
    record.sizes[size] = await page.evaluate(inventory);
    if (size === "desktop") writeFileSync(join(out, `navigation-${id}.json`), JSON.stringify(record.sizes[size].navigation_labels, null, 1));
    delete record.sizes[size].navigation_labels;
    if (flag("scramble")) await page.evaluate(scramble);
    await page.screenshot({ path: join(out, `${id}-${size}.png`) });
    await page.screenshot({ path: join(out, `${id}-${size}-full.png`), fullPage: true }).catch(() => {});
  }
  // the page is read again once, so that the next one can be reached through menus that are legible again
  if (flag("scramble")) { await page.setViewportSize(SIZES.desktop); await page.reload().catch(() => {}); await page.waitForTimeout(1200); }
  writeFileSync(join(out, `inventory-${id}.json`), JSON.stringify(record, null, 1));
  console.log(`  captured ${name}: 3 sizes, ${record.sizes.desktop.custom_properties.reduce((n, t) => n + Object.keys(t.properties).length, 0)} custom properties, ${sheets.size} stylesheets so far`);
  return { page: name, path: record.path, files: [`inventory-${id}.json`, `navigation-${id}.json`, ...Object.keys(SIZES).flatMap((s) => [`${id}-${s}.png`, `${id}-${s}-full.png`])] };
}

const [browser, driven] = await start();
const page = await (await browser.newContext({ viewport: SIZES.desktop })).newPage();
const captured = [];
try {
  if (auto.length) {
    for (const [name, target] of auto) { await page.goto(target, { waitUntil: "networkidle" }).catch(() => page.goto(target)); captured.push(await capture(page, name)); }
  } else {
    const ask = createInterface({ input: process.stdin, output: process.stdout });
    await page.goto(address).catch(() => {});
    console.log(`\nA ${driven} window is open on ${new URL(address).host}. Sign in there if the site asks.\n`);
    const names = [...named];
    for (;;) {
      const name = names.length ? names.shift() : (await ask.question("Name of the next page to capture (leave empty to finish): ")).trim();
      if (!name) break;
      const answer = (await ask.question(`Open "${name}" in the browser window, wait until it is fully shown, then press Enter here (s to skip): `)).trim().toLowerCase();
      if (answer !== "s") captured.push(await capture(page, name));
      if (!names.length && named.length) break;
    }
    ask.close();
  }
} finally {
  await browser.close();
}
writeFileSync(join(out, "manifest.json"), JSON.stringify({ captured_on: new Date().toISOString().slice(0, 10), host: new URL(address).host, browser: driven,
  text_scrambled_in_screenshots: flag("scramble"), sizes: SIZES, pages: captured, stylesheets: [...sheets.values()],
  holds: "screenshots, stylesheets, style values, tag and class names, menu and tab labels. No other text of the pages." }, null, 1));
console.log(`\n${captured.length} page(s) captured in the folder "${out}". Look at the screenshots before sharing the folder.`);
