// Autology Console: talk to an Autology engine. Talks only to /api on this origin (forwarded to the engine).
// Security: everything from the engine is inserted as text (never innerHTML); the token lives in sessionStorage.
"use strict";

const C = window.AutologyCommands;
const S = { token: null, me: null, ontology: null, chatId: null, assistant: null, history: [], historyAt: 0 };
const TOKEN_KEY = "autology-console-token";
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

// -- talking to the engine -------------------------------------------------------------------------------------
class EngineError extends Error {
  constructor(status, message, data) { super(message); this.status = status; this.data = data; }
}

async function api(method, path, body) {
  const response = await fetch("/api/" + path, {
    method,
    headers: { "Authorization": "Bearer " + S.token, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const type = response.headers.get("Content-Type") || "";
  const data = type.includes("json") ? await response.json() : await response.text();
  if (response.status === 428 && data && data.checkpoint && !(body && body.justification)) {
    const cp = data.checkpoint;  // the engine asks the person why they need this: ask, then retry once
    const why = window.prompt(`${cp.prompt}\n\nJustification (at least ${cp.min_length} characters):`);
    if (why && why.trim().length >= cp.min_length) {
      if (method === "GET") return api(method, path + (path.includes("?") ? "&" : "?") +
                                       "justification=" + encodeURIComponent(why.trim()));
      return api(method, path, { ...(body || {}), justification: why.trim() });
    }
  }
  if (!response.ok) {
    if (response.status === 401) signOut("Your session is no longer valid. Sign in again.");
    throw new EngineError(response.status, (data && data.error) || response.statusText, data);
  }
  return data;
}

const can = (p) => S.me && (S.me.permissions.includes("admin") || S.me.permissions.includes(p));

// -- the conversation ------------------------------------------------------------------------------------------
function scrollDown() { const t = $("thread"); t.scrollTop = t.scrollHeight; }

function say(text) {
  $("thread").append(el("div", { class: "msg user" }, text));
  scrollDown();
}

function reply(...nodes) {
  const node = el("div", { class: "msg engine" }, el("div", { class: "from" }, "Engine"), ...nodes);
  $("thread").append(node);
  scrollDown();
  return node;
}

function card(title, ...children) { return el("div", { class: "card" }, title ? el("h3", {}, title) : null, ...children); }
function errorCard(err) {
  const status = err.status ? ` (${err.status})` : "";
  return el("div", { class: "card error" }, el("h3", {}, "The engine refused" + status), el("p", {}, err.message));
}
function pill(text) { return el("span", { class: "pill " + String(text) }, String(text).replace(/_/g, " ")); }
function idLink(id) { return el("button", { type: "button", class: "idlink", onclick: () => run(`/object ${id}`) }, id); }
function cmdButton(label, command) { return el("button", { type: "button", onclick: () => run(command) }, label); }

function fmt(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function table(columns, rows) {
  return el("table", {}, el("thead", {}, el("tr", {}, columns.map((c) => el("th", {}, c)))),
            el("tbody", {}, rows.map((r) => el("tr", {}, r.map((cell) => el("td", {}, cell))))));
}

// -- commands --------------------------------------------------------------------------------------------------
const HANDLERS = {
  help() {
    return card("What you can say",
      el("p", {}, "Ask in plain language, or use a command. Click any id to look at it."),
      table(["Command", "What it does"], C.COMMANDS.map((c) => [el("code", {}, c.usage), c.summary])),
      el("p", { class: "why" }, S.assistant === false
        ? "This engine has no AI assistant configured: plain language is matched to its questions, objects and goals."
        : "Plain language goes to the engine's governed assistant, which acts as you and cannot decide reviews."));
  },

  ontology() {
    const o = S.ontology;
    return card(`${o.ref}`, o.description ? el("p", {}, o.description) : null,
      table(["Entity", "States", "Also called"], Object.entries(o.entities).map(([n, e]) => [
        el("button", { type: "button", class: "idlink", onclick: () => run(`/objects ${n}`) }, n),
        e.states.join(", "), (e.aliases || []).join(", ")])),
      el("p", {}, el("strong", {}, "Goals: "), Object.entries(o.goals).map(([n, g]) => `${n} (${g.description || g.target})`).join("; ")),
      el("p", {}, el("strong", {}, `Rules (${o.rules.length}): `), o.rules.map((r) => r.description || r.id).join(" · ")));
  },

  async objects(args) {
    const type = args[0];
    if (!type) return card("Which type?", el("p", {}, "Try ", el("code", {}, "/objects " + Object.keys(S.ontology.entities)[0])));
    const data = await api("GET", "objects?type=" + encodeURIComponent(type) + "&limit=50");
    if (!data.items.length) return card(`No ${type} objects you may see`);
    const attrs = [...new Set(data.items.flatMap((i) => Object.keys(i.attributes)))].filter((a) => a !== "status").slice(0, 5);
    return card(`${data.total} ${type} object${data.total === 1 ? "" : "s"}`,
      table(["id", "status", ...attrs], data.items.map((i) => [idLink(i.id), pill(i.attributes.status || "—"),
                                                                ...attrs.map((a) => fmt(i.attributes[a]))])));
  },

  async object(args) {
    const id = args[0];
    if (!id) return card("Which object?", el("p", {}, "Try ", el("code", {}, "/object CL-1")));
    const o = await api("GET", "objects/" + encodeURIComponent(id));
    let lineage = null;
    try { lineage = await api("GET", "objects/" + encodeURIComponent(id) + "/lineage"); } catch (e) { /* optional */ }
    const fns = Object.entries(o.functions || {});
    const loads = (lineage && lineage.loads) || [];
    const runnable = Object.values(S.ontology.case_templates || {}).some((t) => t.root === o.type) && can("run");
    return card(`${o.type} ${o.id}`,
      table(["Attribute", "Value"], Object.entries(o.attributes).map(([k, v]) => [k, fmt(v)])
        .concat(fns.map(([k, v]) => [el("span", {}, k, el("span", { class: "why" }, " (calculated)")), fmt(v)]))),
      (o.links || []).length ? el("p", {}, el("strong", {}, "Linked: "),
        ...o.links.flatMap((l, i) => [i ? ", " : "", `${l.direction === "out" ? "" : "← "}${l.kind} `, idLink(l.id)])) : null,
      loads.length ? el("p", { class: "why" }, `Data from: ${loads.map((l) => `${l.pipeline}/${l.source} row ${l.row} (${l.action})`).join("; ")}`) : null,
      runnable ? el("div", { class: "actions" }, cmdButton(`Ask an agent to work on ${o.id}`, `/run ${o.id}`)) : null);
  },

  async ask(args, options) {
    const id = args[0];
    if (!id) return card("Which question?", el("p", {}, "Pick one on the left, or ", el("code", {}, "/ontology")));
    const params = Object.fromEntries(Object.entries(options).map(([k, v]) => [k, C.typed(v)]));
    const data = await api("POST", "questions/" + encodeURIComponent(id), { params });
    const q = (S.ontology.questions || []).find((x) => x.id === id);
    const answer = data.answer;
    return card(q ? q.question : id, Array.isArray(answer)
      ? (answer.length ? el("p", {}, ...answer.flatMap((a, i) => [i ? ", " : "", idLink(String(a))])) : el("p", {}, "None."))
      : el("p", { class: "text" }, fmt(answer)));
  },

  async run(args, options) {
    const root = args[0];
    if (!root) return card("Which object?", el("p", {}, "Try ", el("code", {}, "/run CL-4")));
    let template = options.template;
    if (!template) {
      const obj = await api("GET", "objects/" + encodeURIComponent(root));
      const match = Object.entries(S.ontology.case_templates || {}).filter(([, t]) => t.root === obj.type);
      if (!match.length) return card(`Nothing to run on a ${obj.type}`, el("p", {}, "No case template starts from this type."));
      template = match[0][0];
    }
    const body = { case_template: template, root };
    if (options.goal) body.goal = options.goal;
    if (options.agent) body.agent = options.agent;
    const runOut = await api("POST", "runs", body);
    refreshReviews();
    if (runOut.hidden) return card(`Run ${runOut.run_id}: ${runOut.status.replace(/_/g, " ")}`, el("p", {}, runOut.detail));
    return runCard(runOut);
  },

  async runs(args) {
    const status = args[0];
    const data = await api("GET", "runs?limit=20" + (status ? "&status=" + encodeURIComponent(status) : ""));
    if (!data.items.length) return card("No runs" + (status ? ` with status ${status}` : ""));
    return card("Recent runs", table(["Run", "Case", "Goal", "Status", "Started"], data.items.map((r) => [
      el("button", { type: "button", class: "idlink", onclick: () => run(`/explain ${r.run_id}`) }, r.run_id),
      r.case_id, r.goal, pill(r.status), new Date(r.created_at).toLocaleString()])));
  },

  async explain(args) {
    if (!args[0]) return card("Which run?", el("p", {}, "Try ", el("code", {}, "/runs")));
    return runCard(await api("GET", "runs/" + encodeURIComponent(args[0])));
  },

  async reviews() {
    if (!can("review")) return card("You do not decide reviews", el("p", {}, "Your account has no review permission."));
    const data = await api("GET", "reviews?status=pending");
    $("review-count").textContent = data.items.length;
    if (!data.items.length) return card("Nothing is waiting for you");
    return el("div", {}, data.items.map(reviewCard));
  },

  async proposals() {
    const data = await api("GET", "proposals");
    const open = data.items.filter((p) => p.status === "pending");
    if (!open.length) return card("No proposals waiting");
    return card("Runs the assistant proposed", ...open.map((p) => el("div", { class: "actions" },
      el("span", {}, `${p.body.goal || ""} on ${p.body.root || p.body.case_id || "case"}`),
      el("button", { type: "button", class: "good", onclick: (e) => decideProposal(e, p.proposal_id, true) }, "Confirm"),
      el("button", { type: "button", class: "bad", onclick: (e) => decideProposal(e, p.proposal_id, false) }, "Decline"))));
  },

  async outcomes() {
    const data = await api("GET", "outcomes");
    const actions = Object.entries(data.actions || {});
    return card("Decisions and what happened afterwards",
      actions.length ? table(["Action", "Judged", "Good", "Bad"], actions.map(([n, s]) => [n, s.judged, s.good, s.bad]))
        : el("p", {}, "No outcomes recorded yet."),
      ...(data.suggestions || []).map((s) => el("p", { class: "why" }, "Suggestion: " + s)));
  },

  clear() {
    $("thread").replaceChildren();
    S.chatId = null;
    return null;
  },
};

function runCard(r) {
  const steps = (r.steps || []).map((s) => el("li", {},
    el("div", {}, el("strong", {}, s.action), " ", pill(s.verdict === "allow" ? (s.outcome || "done") : s.verdict),
       s.reviewer ? el("span", { class: "why" }, ` approved by ${s.reviewer}`) : null),
    s.message ? el("div", {}, s.message) : null,
    s.explanation ? el("div", { class: "why" }, s.explanation) : null));
  const esc = r.escalation;
  const node = card(`Run ${r.run_id} on ${r.case_id}`,
    el("p", {}, pill(r.status), ` · goal ${r.goal}`, r.audit_verified === false ? " · audit does NOT verify" : ""),
    steps.length ? el("ol", { class: "steps" }, steps) : el("p", { class: "why" }, "No steps yet."),
    esc ? el("p", {}, el("strong", {}, "Waiting on / handed to: "), `${esc.to}: ${esc.reason}`) : null,
    (r.write_back_conflicts || []).length ? el("p", { class: "why" },
      `Changed elsewhere meanwhile: ${r.write_back_conflicts.map((c) => `${c.type}.${c.attribute}`).join(", ")}`) : null);
  if (r.pending_review && can("review")) {
    node.append(el("div", { class: "actions" }, cmdButton("Review it now", "/reviews")));
  }
  return node;
}

function reviewCard(rv) {
  const req = rv.request || {};
  const comment = el("input", { placeholder: "Comment (required to decline)", "aria-label": "Comment" });
  const node = card(req.description || req.action,
    el("p", {}, el("code", {}, req.action), ` · case ${req.case_id} · needs ${rv.reviewers.join(", ")}`),
    (req.reasons || []).length ? el("ul", {}, req.reasons.map((x) => el("li", {}, x))) : null,
    Object.keys(req.facts || {}).length ? table(["Fact the rules used", "Value"],
      Object.entries(req.facts).map(([k, v]) => [k, fmt(v)])) : null,
    req.explanation ? el("p", { class: "why" }, req.explanation) : null);
  const decide = async (approved, buttons) => {
    if (!approved && !comment.value.trim()) { comment.focus(); return; }
    buttons.forEach((b) => { b.disabled = true; });
    try {
      const out = await api("POST", `reviews/${rv.review_id}/decision`, { approved, comment: comment.value.trim() });
      node.replaceChildren(el("h3", {}, `${approved ? "Approved" : "Declined"}: ${req.action}`),
        el("p", {}, "The run is now ", pill(out.status || out.run_status || "updated"), "."),
        out.run_id ? el("div", { class: "actions" }, cmdButton("See the run", `/explain ${out.run_id}`)) : null);
      refreshReviews();
    } catch (err) {
      node.append(errorCard(err));
      buttons.forEach((b) => { b.disabled = false; });
    }
  };
  const approve = el("button", { type: "button", class: "good" }, "Approve");
  const decline = el("button", { type: "button", class: "bad" }, "Decline");
  approve.onclick = () => decide(true, [approve, decline]);
  decline.onclick = () => decide(false, [approve, decline]);
  node.append(el("div", { class: "actions" }, comment, approve, decline));
  return node;
}

async function decideProposal(event, id, confirm) {
  event.target.disabled = true;
  try {
    const out = await api("POST", `proposals/${id}/decision`, { confirm });
    reply(confirm && out.run_id ? runCard(out) : card(confirm ? "Confirmed" : "Declined"));
  } catch (err) {
    reply(errorCard(err));
  }
}

// -- plain language ---------------------------------------------------------------------------------------------
async function talk(text) {
  if (S.assistant !== false) {
    try {
      const out = await api("POST", "chat", { message: text, chat_id: S.chatId });
      S.assistant = true;
      S.chatId = out.chat_id;
      updateAssistantNote();
      const used = (out.tool_calls || []).map((t) => t.name).filter(Boolean);
      return card(null, el("div", { class: "text" }, out.reply || "(no answer)"),
        used.length ? el("p", { class: "why" }, `Looked at: ${[...new Set(used)].join(", ")}`) : null,
        used.includes("start_run") ? el("div", { class: "actions" }, cmdButton("See proposals to confirm", "/proposals")) : null);
    } catch (err) {
      if (err.status !== 404) return errorCard(err);
      S.assistant = false;  // no assistant on this engine: fall back to matching against the ontology
      updateAssistantNote();
    }
  }
  const options = C.suggest(text, S.ontology, 5);
  if (C.isGreeting(text)) {
    return card(`Hello ${S.me.name}`, el("p", {}, "I can answer the engine's questions, show its objects and start or explain its work. " +
      "This engine has no AI assistant switched on, so short questions about its data work best."),
      el("div", { class: "actions" }, cmdButton("What can I say?", "/help"), cmdButton("What does it know?", "/ontology"),
         ...(S.ontology.questions || []).slice(0, 2).map((q) => cmdButton(q.question, `/ask ${q.id}`))));
  }
  if (!options.length) {
    return card("I could not match that", el("p", {}, "This engine has no AI assistant, so I match what you type to its questions, objects and goals. Try ", el("code", {}, "/help"), "."));
  }
  if (options[0].score >= 0.75 && !options[0].command.startsWith("/run")) {
    const first = await execute(options[0].command);
    const others = options.slice(1);
    return el("div", {}, el("p", { class: "why" }, `Answering with ${options[0].command}`), first,
      others.length ? card("Or did you mean", el("div", { class: "suggestions" }, others.map((o) => cmdButton(o.label, o.command)))) : null);
  }
  return card("Did you mean", el("div", { class: "suggestions" }, options.map((o) => cmdButton(o.label, o.command))));
}

async function execute(input) {
  const parsed = C.parse(input);
  if (parsed.command === null) return talk(parsed.text);
  if (!parsed.known) return card(`Unknown command /${parsed.command}`, el("p", {}, "Type ", el("code", {}, "/help"), "."));
  try {
    return await HANDLERS[parsed.command](parsed.args, parsed.options);
  } catch (err) {
    return err instanceof EngineError ? errorCard(err) : errorCard({ message: String(err.message || err) });
  }
}

async function run(input) {
  const text = String(input).trim();
  if (!text) return;
  S.history.push(text);
  S.historyAt = S.history.length;
  if (text !== "/clear") say(text);
  const button = $("send");
  button.disabled = true;
  const thinking = reply(el("p", { class: "why" }, "…"));
  try {
    const node = await execute(text);
    if (node) thinking.replaceChildren(el("div", { class: "from" }, "Engine"), node);
    else thinking.remove();
  } finally {
    button.disabled = false;
    scrollDown();
  }
}

// -- composer: slash hints and history ---------------------------------------------------------------------------
function showHints() {
  const value = $("message").value;
  const hints = $("hints");
  if (!value.startsWith("/") || value.includes(" ")) { hints.hidden = true; return; }
  const matches = C.completions(value);
  hints.replaceChildren(...matches.map((c) => el("button", { type: "button", onclick: () => {
    $("message").value = "/" + c.name + " ";
    hints.hidden = true;
    $("message").focus();
  } }, el("code", {}, c.usage), el("span", { class: "muted small" }, c.summary))));
  hints.hidden = !matches.length;
}

// -- sidebar ----------------------------------------------------------------------------------------------------
function fillSide() {
  const o = S.ontology;
  $("engine-ref").textContent = o.ref;
  $("side-ontology").textContent = `${o.ref} · ${Object.keys(o.entities).length} entities, ${o.rules.length} rules`;
  $("side-questions").replaceChildren(...(o.questions || []).map((q) => el("li", {},
    el("button", { type: "button", title: q.id, onclick: () => run(`/ask ${q.id}`) }, q.question))));
  $("side-entities").replaceChildren(...Object.keys(o.entities).map((n) => el("li", {},
    el("button", { type: "button", onclick: () => run(`/objects ${n}`) }, n))));
  $("side-goals").replaceChildren(...Object.entries(o.goals).map(([n, g]) => el("li", {}, el("strong", {}, n), " — ", g.description || g.target)));
  $("side-reviews").hidden = !can("review");
  updateAssistantNote();
}

function updateAssistantNote() {
  $("side-assistant").textContent = S.assistant === false
    ? "No AI assistant on this engine: plain language is matched to its questions and objects."
    : S.assistant ? "AI assistant: on (it acts as you and cannot decide reviews)." : "";
}

async function refreshReviews() {
  if (!can("review")) return;
  try { $("review-count").textContent = (await api("GET", "reviews?status=pending")).items.length; } catch (e) { /* ignore */ }
}

// -- sign-in (API token, or company account via the engine's OpenID Connect) ------------------------------------
function readToken() { try { return sessionStorage.getItem(TOKEN_KEY); } catch (e) { return S.token; } }
function saveToken(t) {
  S.token = t;
  try { if (t) sessionStorage.setItem(TOKEN_KEY, t); else sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* memory only */ }
}

function signOut(message) {
  saveToken(null);
  S.me = null; S.chatId = null; S.assistant = null;
  $("thread").replaceChildren();
  $("app").hidden = true; $("who").hidden = true; $("signin").hidden = false;
  if (message) $("signin-note").textContent = message;
}

async function enter() {
  try {
    S.me = await api("GET", "me");
    S.ontology = await api("GET", "ontology");
    if (typeof S.ontology.assistant === "boolean") S.assistant = S.ontology.assistant;  // older engines: find out on first use
  } catch (err) {
    signOut(err.status === 401 ? "That token was not accepted." : "Could not connect: " + err.message);
    return;
  }
  $("signin").hidden = true; $("app").hidden = false; $("who").hidden = false;
  $("who-name").textContent = `${S.me.name} · ${S.me.permissions.join(", ")}`;
  fillSide();
  refreshReviews();
  reply(card(`Connected to ${S.ontology.ref}`,
    el("p", {}, "Ask a question in your own words, pick one on the left, or type ", el("code", {}, "/"), " for commands."),
    el("div", { class: "actions" }, cmdButton("What can I say?", "/help"), cmdButton("What does it know?", "/ontology"),
       can("review") ? cmdButton("What is waiting for me?", "/reviews") : null)));
  $("message").focus();
}

function b64url(bytes) {
  let text = "";
  bytes.forEach((b) => { text += String.fromCharCode(b); });
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function randomString(n) { const b = new Uint8Array(n); crypto.getRandomValues(b); return b64url(b); }
const redirectUri = () => window.location.origin + "/";

async function startSso(config) {
  const verifier = randomString(32), state = randomString(16), nonce = randomString(16);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  try { sessionStorage.setItem("autology-console-sso", JSON.stringify({ verifier, state, nonce })); }
  catch (e) { signOut("Sign-in needs this browser to allow session storage."); return; }
  const url = new URL(config.authorization_endpoint);
  url.search = new URLSearchParams({ response_type: "code", client_id: config.client_id, redirect_uri: redirectUri(),
    scope: config.scopes, state, nonce, code_challenge: b64url(new Uint8Array(digest)), code_challenge_method: "S256" }).toString();
  window.location.assign(url.toString());
}

async function finishSso(params) {
  let pending = null;
  try { pending = JSON.parse(sessionStorage.getItem("autology-console-sso")); sessionStorage.removeItem("autology-console-sso"); }
  catch (e) { /* none */ }
  history.replaceState(null, "", "/");
  if (params.get("error")) { signOut("Sign-in failed: " + (params.get("error_description") || params.get("error"))); return; }
  if (!pending || params.get("state") !== pending.state) { signOut("Sign-in failed: the response did not match this browser's request."); return; }
  const response = await fetch("/api/auth/token", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: params.get("code"), code_verifier: pending.verifier, redirect_uri: redirectUri(), nonce: pending.nonce }) });
  const data = await response.json();
  if (!response.ok) { signOut("Sign-in failed: " + data.error); return; }
  saveToken(data.token);
  enter();
}

async function offerSso() {
  try {
    const response = await fetch("/api/auth/config");
    const config = await response.json();
    if (response.ok && config.oidc) { $("sso").hidden = false; $("sso-button").onclick = () => startSso(config); }
  } catch (e) { /* tokens only */ }
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    const info = await (await fetch("/console/info")).json();
    $("engine-at").textContent = "Engine: " + info.engine;
  } catch (e) { /* informational */ }
  $("signin-form").addEventListener("submit", (e) => {
    e.preventDefault();
    saveToken($("token").value.trim());
    $("token").value = "";
    enter();
  });
  $("sign-out").addEventListener("click", () => signOut());
  $("side-reviews").addEventListener("click", () => run("/reviews"));
  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("message").value;
    $("message").value = "";
    $("hints").hidden = true;
    run(text);
  });
  $("message").addEventListener("input", showHints);
  $("message").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); }
    else if (e.key === "Escape") $("hints").hidden = true;
    else if (e.key === "ArrowUp" && !$("message").value && S.history.length) {
      e.preventDefault();
      S.historyAt = Math.max(0, S.historyAt - 1);
      $("message").value = S.history[S.historyAt];
    }
  });
  offerSso();
  const params = new URLSearchParams(window.location.search);
  if (params.has("code") || params.has("error")) { finishSso(params); return; }
  const saved = readToken();
  if (saved) { S.token = saved; enter(); }
});
