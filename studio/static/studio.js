// Autology Studio (interim shell). Everything here is presentation: the platform decides every permission, check
// and stage. Security: data from the platform is inserted as text nodes only, never parsed as markup; the token lives in
// sessionStorage (this tab only) and is sent as a bearer token, so there is no cookie to forge.
"use strict";

const TOKEN_KEY = "autology-studio-token";
const LABELS = { draft: "Draft", simulation: "Simulation", pilot: "Pilot", production: "Production" };
const S = { token: null, me: null, useCases: [], selected: null, detail: null };

const $ = (id) => document.getElementById(id);
function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const c of children) if (c !== null && c !== undefined) e.append(typeof c === "string" ? document.createTextNode(c) : c);
  return e;
}
function readToken() { try { return sessionStorage.getItem(TOKEN_KEY); } catch (e) { return S.token; } }
function saveToken(t) {
  S.token = t;
  try { if (t) sessionStorage.setItem(TOKEN_KEY, t); else sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* memory only */ }
}

async function api(method, path, body) {
  const headers = { "Authorization": "Bearer " + (readToken() || S.token || "") };
  const init = { method, headers, redirect: "error" };
  if (body !== undefined) { headers["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
  const resp = await fetch(path, init);
  let data = {};
  try { data = await resp.json(); } catch (e) { data = { error: "unexpected answer from the platform" }; }
  if (resp.status === 401) { signOut(); throw new Error("Your token was refused. Sign in again."); }
  if (!resp.ok) { const err = new Error(data.error || ("HTTP " + resp.status)); err.data = data; throw err; }
  return data;
}

function wsPath(rest) { return "/platform/workspaces/" + encodeURIComponent(S.me.workspace.id) + "/use-cases" + (rest || ""); }
function nextStage(stage, stages) { const i = stages.indexOf(stage); return i >= 0 && i + 1 < stages.length ? stages[i + 1] : null; }

async function load() {
  S.me = await api("GET", "/platform/me");
  $("ws-name").textContent = S.me.workspace.name;
  $("who-name").textContent = S.me.member;
  $("who-admin").hidden = !S.me.workspace_admin;
  $("new-uc").hidden = !S.me.workspace_admin;
  $("signin").hidden = true; $("app").hidden = false; $("who").hidden = false;
  await refreshList();
}

async function refreshList() {
  S.useCases = (await api("GET", wsPath())).items;
  const list = $("uc-list"); list.replaceChildren();
  $("uc-empty").hidden = S.useCases.length > 0;
  for (const uc of S.useCases) {
    list.append(el("li", {}, el("button", { type: "button", "data-id": uc.id, "aria-current": String(uc.id === S.selected), onclick: () => select(uc.id) },
      el("span", {}, uc.name, el("br"), el("span", { class: "muted small" }, uc.id)),
      el("span", { class: "stage stage-" + uc.stage }, LABELS[uc.stage] + (uc.stale ? " · stale" : "")))));
  }
  if (S.selected) await select(S.selected);
}

async function select(id) {
  S.selected = id;
  for (const b of $("uc-list").querySelectorAll("button")) b.setAttribute("aria-current", String(b.dataset.id === id));
  const uc = await api("GET", wsPath("/" + encodeURIComponent(id)));
  S.detail = uc;
  $("detail-empty").hidden = true; $("detail-body").hidden = false;
  $("d-name").textContent = uc.name;
  $("d-meta").textContent = `${uc.id} · ${uc.ontology} · fingerprint ${uc.fingerprint.slice(0, 12)} · `
    + (uc.origin === "template" ? `created from template ${uc.template}` : "configured by the operator");
  const stepper = $("d-stepper"); stepper.replaceChildren();
  const at = uc.stages.indexOf(uc.stage);
  uc.stages.forEach((s, i) => stepper.append(el("li", {
    class: (i < at ? "done" : i === at ? "current" : "") + (s === "production" ? " locked" : ""),
    "aria-current": i === at ? "step" : "false" }, LABELS[s] + (s === "production" ? " (not authorised)" : ""))));
  const warn = uc.integrity_problem || (uc.stale ? "The configuration changed after this stage was granted: the checks that granted it no longer describe what runs." : "");
  $("d-warn").hidden = !warn; $("d-warn").textContent = warn;
  const next = nextStage(uc.stage, uc.stages);
  $("d-checks-title").textContent = next ? "Readiness for " + LABELS[next] : "Readiness";
  $("d-checks").replaceChildren(); $("d-check").disabled = !next;
  const history = $("d-history"); history.replaceChildren();
  $("d-history-empty").hidden = uc.history.length > 0;
  for (const h of uc.history.slice().reverse()) {
    history.append(el("li", {}, `${LABELS[h.from_stage]} → ${LABELS[h.to_stage]} by ${h.by}, ${new Date(h.at).toLocaleString()}`,
      el("br"), el("span", { class: "muted small" }, h.reason)));
  }
  const admin = S.me.workspace_admin;
  $("d-move").hidden = !admin;
  if (admin) {
    const to = $("d-to"); to.replaceChildren();
    for (const s of uc.stages) {
      if (s === uc.stage) continue;
      const i = uc.stages.indexOf(s);
      const opt = el("option", { value: s }, LABELS[s] + (i < at ? " (back)" : ""));
      if (s === "production" || i > at + 1) opt.disabled = true;
      to.append(opt);
    }
    if (next && next !== "production") to.value = next;
    $("d-error").textContent = "";
  }
}

function showChecks(checks) {
  const ul = $("d-checks"); ul.replaceChildren();
  for (const c of checks) ul.append(el("li", { class: c.passed ? "pass" : "fail" }, c.detail));
}

async function runChecks() {
  const next = nextStage(S.detail.stage, S.detail.stages);
  if (!next) return;
  try { showChecks((await api("GET", wsPath("/" + encodeURIComponent(S.detail.id) + "/checks?to=" + next))).checks); }
  catch (e) { $("d-checks").replaceChildren(el("li", { class: "fail" }, e.message)); }
}

async function move(ev) {
  ev.preventDefault();
  $("d-error").textContent = "";
  try {
    await api("POST", wsPath("/" + encodeURIComponent(S.detail.id) + "/stage"), { to: $("d-to").value, reason: $("d-reason").value });
    $("d-reason").value = "";
    await refreshList();
  } catch (e) {
    $("d-error").textContent = e.message;
    if (e.data && e.data.checks) showChecks(e.data.checks);
  }
}

async function openCreate() {
  $("c-error").textContent = "";
  try {
    const t = (await api("GET", "/platform/templates")).items;
    $("c-template").replaceChildren(...t.map((x) => el("option", { value: x.id }, x.name)));
    if (!t.length) $("c-error").textContent = "The platform operator has not approved any template.";
    $("create-form").hidden = false;
  } catch (e) { $("c-error").textContent = e.message; $("create-form").hidden = false; }
}

async function create(ev) {
  ev.preventDefault();
  $("c-error").textContent = "";
  try {
    const uc = await api("POST", wsPath(), { id: $("c-id").value, name: $("c-name").value, template: $("c-template").value });
    $("create-form").hidden = true; $("create-form").reset();
    S.selected = uc.id;
    await refreshList();
  } catch (e) { $("c-error").textContent = e.message; }
}

function signOut() {
  saveToken(null); S.me = null; S.selected = null;
  $("app").hidden = true; $("who").hidden = true; $("signin").hidden = false;
}

document.addEventListener("DOMContentLoaded", () => {
  $("signin-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    $("signin-error").textContent = "";
    saveToken($("token").value.trim()); $("token").value = "";
    try { await load(); } catch (e) { $("signin-error").textContent = e.message; }
  });
  $("sign-out").addEventListener("click", signOut);
  $("d-check").addEventListener("click", runChecks);
  $("d-move").addEventListener("submit", move);
  $("new-uc").addEventListener("click", openCreate);
  $("c-cancel").addEventListener("click", () => { $("create-form").hidden = true; });
  $("create-form").addEventListener("submit", create);
  if (readToken()) load().catch(() => signOut());
});
