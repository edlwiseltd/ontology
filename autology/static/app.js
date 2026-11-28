// Autology inbox: reviews, runs, starting runs, browsing objects. Talks only to this server's /api.
// Security: data is only ever inserted with textContent (never innerHTML); the token lives in sessionStorage.
"use strict";

const state = { token: null, me: null, ontology: null };

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function show(message, kind = "") {
  const s = $("status");
  s.textContent = message;
  s.className = "status " + kind;
}

function readToken() {
  try { return sessionStorage.getItem("autology-token"); } catch (e) { return state.token; }
}

function saveToken(token) {
  state.token = token;
  try {
    if (token) sessionStorage.setItem("autology-token", token);
    else sessionStorage.removeItem("autology-token");
  } catch (e) { /* storage unavailable: keep the token in memory only */ }
}

async function api(method, path, body) {
  const response = await fetch("/api/" + path, {
    method,
    headers: { "Authorization": "Bearer " + state.token, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const type = response.headers.get("Content-Type") || "";
  const data = type.includes("json") ? await response.json() : await response.text();
  if (response.status === 428 && data && data.checkpoint && !(body && body.justification)) {
    // A checkpoint rule asks the person (never the assistant) why they need this. Ask, then retry once.
    const cp = data.checkpoint;
    const why = window.prompt(`${cp.prompt}\n\nJustification (at least ${cp.min_length} characters):`);
    if (why && why.trim().length >= cp.min_length) {
      if (method === "GET") {
        return api(method, path + (path.includes("?") ? "&" : "?") + "justification=" + encodeURIComponent(why.trim()));
      }
      return api(method, path, { ...(body || {}), justification: why.trim() });
    }
  }
  if (!response.ok) {
    if (response.status === 401) signOut("Your session is no longer valid. Sign in again.");
    throw new Error((data && data.error) || response.statusText);
  }
  return data;
}

const can = (permission) => state.me && (state.me.permissions.includes("admin") || state.me.permissions.includes(permission));

function pill(text) { return el("span", { class: "pill " + text }, text.replace("_", " ")); }

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString();
}

function fmtValue(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// -- tabs -----------------------------------------------------------------
const TABS = ["reviews", "runs", "start", "objects", "activity", "assistant"];

function selectTab(name) {
  for (const t of TABS) {
    const selected = t === name;
    $("tab-" + t).setAttribute("aria-selected", String(selected));
    $("tab-" + t).tabIndex = selected ? 0 : -1;
    $("panel-" + t).hidden = !selected;
  }
  if (name === "reviews") loadReviews();
  if (name === "runs") loadRuns();
  if (name === "objects") loadObjects();
  if (name === "activity") loadActivity();
  if (name === "assistant") loadProposals();
}

function setupTabs() {
  for (const t of TABS) $("tab-" + t).addEventListener("click", () => selectTab(t));
  document.querySelector(".tabs").addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    const visible = TABS.filter((t) => !$("tab-" + t).hidden);
    const current = visible.findIndex((t) => $("tab-" + t).getAttribute("aria-selected") === "true");
    const next = visible[(current + (e.key === "ArrowRight" ? 1 : visible.length - 1)) % visible.length];
    selectTab(next);
    $("tab-" + next).focus();
  });
}

// -- reviews ----------------------------------------------------------------
function reviewCard(review) {
  const req = review.request || {};
  const comment = el("input", { type: "text", "aria-label": "Comment for " + review.action,
    placeholder: "Comment (required to decline)" });
  const decide = async (approved, button) => {
    const verb = approved ? "approve" : "decline";
    if (!approved && !comment.value.trim()) {
      show("Add a comment saying why you decline.", "error");
      comment.focus();
      return;
    }
    button.disabled = true;
    try {
      const run = await api("POST", `reviews/${review.review_id}/decision`, { approved, comment: comment.value });
      show(`You chose to ${verb} ${review.action}. The run is now ${run.status.replace("_", " ")}.`, "ok");
      loadReviews();
    } catch (err) {
      show(`Could not ${verb}: ${err.message}`, "error");
      button.disabled = false;
    }
  };
  const approve = el("button", { type: "button", class: "primary" }, "Approve");
  const decline = el("button", { type: "button", class: "danger" }, "Decline");
  approve.addEventListener("click", () => decide(true, approve));
  decline.addEventListener("click", () => decide(false, decline));

  const facts = el("dl", { class: "facts" });
  for (const [k, v] of Object.entries(req.facts || {})) facts.append(el("dt", {}, k), el("dd", {}, fmtValue(v)));
  const subject = req.binding && Object.keys(req.binding).length
    ? Object.entries(req.binding).flatMap(([entity, id]) => {
        const values = ((req.view || {})[entity] || {})[id] || {};
        return [el("h4", {}, `${entity} ${id}`),
          el("dl", { class: "facts" }, ...Object.entries(values).flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, fmtValue(v))]))];
      })
    : [];

  return el("article", { class: "card review" },
    el("h3", {}, req.description || review.action),
    el("p", { class: "muted" }, `${review.action} · case ${req.case_id || "?"} · needs ${review.reviewers.join(", ")} · requested ${fmtTime(review.created_at)}`),
    el("ul", { class: "reasons" }, ...(req.reasons || []).map((r) => el("li", {}, r))),
    req.rule_ids && req.rule_ids.length ? el("p", { class: "muted" }, "Rules: " + req.rule_ids.join(", ")) : null,
    Object.keys(req.facts || {}).length ? el("h4", {}, "Facts the rules used") : null,
    Object.keys(req.facts || {}).length ? facts : null,
    ...subject,
    req.history && req.history.length ? el("p", { class: "history" }, "So far: " + req.history.join(" → ")) : null,
    el("div", { class: "decide" }, comment, approve, decline),
  );
}

async function loadReviews() {
  const box = $("reviews");
  if (!can("review")) {
    box.replaceChildren(el("p", { class: "empty" }, "You don't have review permission."));
    $("review-count").textContent = "0";
    return;
  }
  try {
    const { items } = await api("GET", "reviews");
    $("review-count").textContent = String(items.length);
    box.replaceChildren(...(items.length ? items.map(reviewCard) : [el("p", { class: "empty" }, "Nothing is waiting for you.")]));
  } catch (err) {
    show("Could not load reviews: " + err.message, "error");
  }
}

// -- runs -------------------------------------------------------------------
async function loadRuns() {
  const status = $("run-status").value;
  try {
    const { items } = await api("GET", "runs" + (status ? "?status=" + encodeURIComponent(status) : ""));
    const rows = items.map((r) => {
      const tr = el("tr", { class: "clickable", tabindex: "0" },
        el("td", {}, r.case_id), el("td", {}, r.goal), el("td", {}, r.agent || ""), el("td", {}, pill(r.status)),
        el("td", {}, fmtTime(r.updated_at)));
      const open = () => showRun(r.run_id);
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
      return tr;
    });
    const body = $("runs-table").tBodies[0];
    body.replaceChildren(...(rows.length ? rows : [el("tr", {}, el("td", { colspan: "5", class: "empty" }, "No runs yet."))]));
  } catch (err) {
    show("Could not load runs: " + err.message, "error");
  }
}

async function showRun(runId) {
  const box = $("run-detail");
  try {
    const run = await api("GET", "runs/" + encodeURIComponent(runId));
    const steps = el("table", {},
      el("thead", {}, el("tr", {}, ...["#", "Action", "Verdict", "Outcome", "By", "Reviewer", "Note"].map((h) => el("th", {}, h)))),
      el("tbody", {}, ...run.steps.map((s) => el("tr", {},
        el("td", {}, s.index), el("td", {}, s.action), el("td", {}, pill(s.verdict)), el("td", {}, s.outcome || ""),
        el("td", {}, s.executed_by || ""), el("td", {}, s.reviewer || ""), el("td", {}, s.message || "")))));
    const children = [
      el("div", { class: "section-head" },
        el("h3", {}, `Case ${run.case_id} · ${run.goal}`),
        el("span", {}, pill(run.status), " ", pill(run.audit_verified ? "verified" : "tampered"))),
      run.escalation ? el("p", {}, `${run.escalation.reason} (to ${run.escalation.to})`) : null,
      run.escalation && run.escalation.details && run.escalation.details.length
        ? el("ul", { class: "reasons" }, ...run.escalation.details.map((d) => el("li", {}, d))) : null,
      el("div", { class: "table-wrap" }, steps),
    ];
    if (["deferred", "paused"].includes(run.status) && can("run")) {
      const resume = el("button", { type: "button" }, "Resume now");
      resume.addEventListener("click", async () => {
        try {
          const next = await api("POST", `runs/${runId}/resume`, { force: true });
          show("Run is now " + next.status.replace("_", " ") + ".", "ok");
          showRun(runId);
          loadRuns();
        } catch (err) { show("Could not resume: " + err.message, "error"); }
      });
      children.push(el("div", { class: "decide" }, resume));
    }
    box.replaceChildren(...children.filter(Boolean));
    box.hidden = false;
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    show("Could not load the run: " + err.message, "error");
  }
}

// -- start a run --------------------------------------------------------------
function fillStartForm() {
  const agents = (state.ontology && state.ontology.agents) || {};
  const agentSel = $("start-agent");
  agentSel.replaceChildren(...Object.keys(agents).map((a) => el("option", { value: a }, a)));
  const fillGoals = () => {
    const goals = (agents[agentSel.value] || {}).goals || [];
    $("start-goal").replaceChildren(...goals.map((g) => el("option", { value: g }, g)));
  };
  agentSel.addEventListener("change", fillGoals);
  fillGoals();
  const templates = (state.ontology && state.ontology.case_templates) || {};
  $("start-template").replaceChildren(...Object.entries(templates).map(([t, spec]) =>
    el("option", { value: t }, `${t} (starts at a ${spec.root})`)));
  $("free-form").hidden = !(state.ontology && state.ontology.free_form_cases);
}

async function startRun(event) {
  event.preventDefault();
  const raw = $("start-case").value.trim();
  let body;
  if (raw && !$("free-form").hidden) {
    try {
      body = { case: JSON.parse(raw), case_id: $("start-case-id").value || "case" };
    } catch (err) {
      show("The case data is not valid JSON: " + err.message, "error");
      $("start-case").focus();
      return;
    }
  } else {
    if (!$("start-root").value.trim()) {
      show("Give the id of the object to start from.", "error");
      $("start-root").focus();
      return;
    }
    body = { case_template: $("start-template").value, root: $("start-root").value.trim() };
  }
  const button = event.submitter || $("start-form").querySelector("button");
  button.disabled = true;
  show("Running…");
  try {
    const run = await api("POST", "runs", { agent: $("start-agent").value, goal: $("start-goal").value, ...body });
    show(`Run ${run.run_id} is ${run.status.replace("_", " ")}` + (run.escalation ? `: ${run.escalation.reason}` : "."), run.status === "completed" ? "ok" : "");
    loadReviews();
  } catch (err) {
    show("Could not start the run: " + err.message, "error");
  } finally {
    button.disabled = false;
  }
}

// -- objects ---------------------------------------------------------------------
const JUSTIFY = "***justification required***";

async function loadObjects(justification) {
  const type = $("object-type").value;
  if (!type) return;
  try {
    const why = typeof justification === "string" ? "&justification=" + encodeURIComponent(justification) : "";
    const { total, items } = await api("GET", "objects?type=" + encodeURIComponent(type) + "&limit=200" + why);
    const gated = items.some((i) => Object.values(i.attributes).includes(JUSTIFY));
    $("reveal-objects").hidden = !gated;
    const attrs = [...new Set(items.flatMap((i) => Object.keys(i.attributes)))];
    $("objects-table").tHead.replaceChildren(el("tr", {}, el("th", {}, "id"), ...attrs.map((a) => el("th", {}, a))));
    $("objects-table").tBodies[0].replaceChildren(...items.map((i) =>
      el("tr", {}, el("td", {}, i.id), ...attrs.map((a) => el("td", {}, fmtValue(i.attributes[a]))))));
    $("object-total").textContent = `${total} visible to you` + (total > items.length ? ` (showing ${items.length})` : "");
  } catch (err) {
    show("Could not load objects: " + err.message, "error");
  }
}

// -- session -----------------------------------------------------------------------
// -- activity: notifications and automations ---------------------------------
async function loadActivity() {
  try {
    const [{ items: notes }, { items: autos }] = await Promise.all([api("GET", "notifications?limit=50"),
                                                                      api("GET", "automations")]);
    $("note-count").textContent = String(notes.length);
    $("notifications").replaceChildren(...(notes.length ? notes.map((n) => el("li", {},
      el("span", { class: "pill " + n.kind }, n.kind), " ", n.message,
      el("span", { class: "muted" }, " · " + fmtTime(n.created_at)),
      n.ref && n.ref.run_id ? el("button", { type: "button", class: "link", "data-run": n.ref.run_id }, "open run") : null,
    )) : [el("li", { class: "empty" }, "No notifications for your roles.")]));
    for (const b of $("notifications").querySelectorAll("button[data-run]")) {
      b.addEventListener("click", () => { selectTab("runs"); showRun(b.dataset.run); });
    }
    $("automations").replaceChildren(...(autos.length ? autos.map((a) => el("div", { class: "card" },
      el("h3", {}, a.name), el("p", {}, a.description || ""),
      el("p", { class: "muted" }, `${a.entity} · when ${a.when || "always"} · ${a.trigger}` +
        (a.run ? ` · runs ${a.run.agent}/${a.run.goal}` : "") + (a.notify ? ` · notifies ${a.notify.roles.join(", ")}` : "")),
      a.recent.length ? el("p", { class: "history" }, "Recent: " + a.recent.map((f) =>
        `${f.instance} ${f.run_status || f.status}`).join(", ")) : el("p", { class: "muted" }, "Not fired yet."),
      can("run") ? el("button", { type: "button", "data-auto": a.name }, "Run now") : null,
    )) : [el("p", { class: "empty" }, "No automations are configured.")]));
    for (const b of $("automations").querySelectorAll("button[data-auto]")) {
      b.addEventListener("click", async () => {
        try {
          const { firings } = await api("POST", `automations/${encodeURIComponent(b.dataset.auto)}/run`, {});
          show(`${b.dataset.auto}: fired for ${firings.length} object(s)`, "ok");
          loadActivity();
        } catch (err) { show("Could not run automation: " + err.message, "error"); }
      });
    }
  } catch (err) {
    show("Could not load activity: " + err.message, "error");
  }
}

// -- assistant ----------------------------------------------------------------
function chatBubble(role, text, tools) {
  return el("div", { class: "bubble " + role },
    el("p", {}, text || (role === "assistant" ? "(no answer)" : "")),
    tools && tools.length ? el("p", { class: "muted tools" }, "Looked up: " + tools.join(", ")) : null);
}

async function loadProposals() {
  try {
    const { items } = await api("GET", "proposals");
    const pending = items.filter((p) => p.status === "pending");
    $("proposals").replaceChildren(...pending.map((p) => {
      const confirm = el("button", { type: "button", class: "primary" }, "Run it");
      const decline = el("button", { type: "button" }, "Decline");
      const decide = async (yes) => {
        try {
          const out = await api("POST", `proposals/${encodeURIComponent(p.proposal_id)}/decision`, { confirm: yes });
          show(yes ? `Run ${out.run_id} is ${String(out.status).replace("_", " ")}.` : "Proposal declined.", "ok");
          loadProposals();
        } catch (err) { show("Could not decide the proposal: " + err.message, "error"); }
      };
      confirm.addEventListener("click", () => decide(true));
      decline.addEventListener("click", () => decide(false));
      return el("div", { class: "card proposal" },
        el("p", {}, `The assistant proposes: ${p.body.goal} on ${p.body.root} (agent ${p.body.agent}). ` +
          "Results are written back to the data. Nothing has run yet."),
        el("div", { class: "decide" }, confirm, decline));
    }));
  } catch (err) {
    show("Could not load proposals: " + err.message, "error");
  }
}

async function sendChat(event) {
  event.preventDefault();
  const input = $("chat-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  $("chat-log").append(chatBubble("user", message));
  const button = $("chat-form").querySelector("button");
  button.disabled = true;
  show("The assistant is working…");
  try {
    const out = await api("POST", "chat", { message, chat_id: state.chatId || undefined });
    state.chatId = out.chat_id;
    $("chat-log").append(chatBubble("assistant", out.reply, out.tool_calls.map((c) => c.name)));
    if (out.tool_calls.some((c) => c.name === "start_run")) loadProposals();
    show("");
  } catch (err) {
    show("The assistant could not answer: " + err.message, "error");
  } finally {
    button.disabled = false;
    input.focus();
  }
}

function signOut(message) {
  saveToken(null);
  state.chatId = null;
  $("chat-log").replaceChildren();
  show("");
  state.me = null;
  $("app").hidden = true;
  $("who").hidden = true;
  $("signin").hidden = false;
  if (message) {
    $("signin").querySelector("p").textContent = message;
  }
}

// -- single sign-on (OpenID Connect, authorization code with PKCE; the server exchanges the code) -------------
function b64url(bytes) {
  let text = "";
  bytes.forEach((b) => { text += String.fromCharCode(b); });
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(n) {
  const bytes = new Uint8Array(n);
  crypto.getRandomValues(bytes);
  return b64url(bytes);
}

const redirectUri = () => window.location.origin + "/";

async function startSso(config) {
  const verifier = randomString(32), stateParam = randomString(16), nonce = randomString(16);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  try {
    sessionStorage.setItem("autology-sso", JSON.stringify({ verifier, state: stateParam, nonce }));
  } catch (e) {
    signOut("Sign-in needs this browser to allow session storage.");
    return;
  }
  const url = new URL(config.authorization_endpoint);
  url.search = new URLSearchParams({
    response_type: "code", client_id: config.client_id, redirect_uri: redirectUri(), scope: config.scopes,
    state: stateParam, nonce, code_challenge: b64url(new Uint8Array(digest)), code_challenge_method: "S256",
  }).toString();
  window.location.assign(url.toString());
}

async function finishSso(params) {
  let pending = null;
  try {
    pending = JSON.parse(sessionStorage.getItem("autology-sso"));
    sessionStorage.removeItem("autology-sso");
  } catch (e) { /* no pending sign-in */ }
  history.replaceState(null, "", "/");  // the code is single-use: keep it out of the address bar and history
  if (params.get("error")) {
    signOut("Sign-in failed: " + (params.get("error_description") || params.get("error")));
    return;
  }
  if (!pending || params.get("state") !== pending.state) {
    signOut("Sign-in failed: the response did not match this browser's request. Try again.");
    return;
  }
  const response = await fetch("/api/auth/token", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: params.get("code"), code_verifier: pending.verifier, redirect_uri: redirectUri(),
                           nonce: pending.nonce }),
  });
  const data = await response.json();
  if (!response.ok) {
    signOut("Sign-in failed: " + data.error);
    return;
  }
  saveToken(data.token);
  enter();
}

async function offerSso() {
  try {
    const response = await fetch("/api/auth/config");
    const config = await response.json();
    if (!response.ok || !config.oidc) return;
    $("sso").hidden = false;
    $("sso-button").onclick = () => startSso(config);
  } catch (e) { /* no single sign-on: tokens only */ }
}

async function enter() {
  try {
    state.me = await api("GET", "me");
  } catch (err) {
    signOut(err.message === "invalid token" ? "That token was not accepted." : "Sign-in failed: " + err.message);
    return;
  }
  $("signin").hidden = true;
  $("app").hidden = false;
  $("who").hidden = false;
  $("who-name").textContent = `${state.me.name} · ${state.me.permissions.join(", ")}`;
  $("tab-start").hidden = !can("run");
  $("tab-reviews").hidden = !can("review");
  if (can("read")) {
    state.ontology = await api("GET", "ontology");
    $("ontology-ref").textContent = state.ontology.ref;
    $("object-type").replaceChildren(...Object.keys(state.ontology.entities).map((e) => el("option", { value: e }, e)));
    fillStartForm();
  }
  selectTab(can("review") ? "reviews" : "runs");
}

document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  $("signin-form").addEventListener("submit", (e) => {
    e.preventDefault();
    saveToken($("token").value.trim());
    $("token").value = "";
    enter();
  });
  $("sign-out").addEventListener("click", () => signOut());
  $("refresh-reviews").addEventListener("click", loadReviews);
  $("refresh-activity").addEventListener("click", loadActivity);
  $("chat-form").addEventListener("submit", sendChat);
  $("chat-new").addEventListener("click", () => { state.chatId = null; $("chat-log").replaceChildren(); });
  $("run-status").addEventListener("change", loadRuns);
  $("object-type").addEventListener("change", () => loadObjects());
  $("reveal-objects").addEventListener("click", () => {
    const why = window.prompt("Some fields need a recorded justification. Why do you need to see them?");
    if (why && why.trim()) loadObjects(why.trim());
  });
  $("start-form").addEventListener("submit", startRun);
  offerSso();
  const params = new URLSearchParams(window.location.search);
  if (params.has("code") || params.has("error")) { finishSso(params); return; }
  const saved = readToken();
  if (saved) { state.token = saved; enter(); }
});
