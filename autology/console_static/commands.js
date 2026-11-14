// Autology Console: command parsing and plain-language matching. No DOM, no network: testable with Node.
"use strict";

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.AutologyCommands = api;
})(typeof self !== "undefined" ? self : this, function () {
  const COMMANDS = [
    { name: "help", usage: "/help", summary: "What you can say to the engine" },
    { name: "ontology", usage: "/ontology", summary: "What the engine knows: entities, goals, rules, questions" },
    { name: "objects", usage: "/objects <Entity>", summary: "List objects of a type, e.g. /objects Claim" },
    { name: "object", usage: "/object <id>", summary: "One object, its links and where its data came from" },
    { name: "ask", usage: "/ask <question id> [name=value ...]", summary: "Answer one of the ontology's questions" },
    { name: "run", usage: "/run <object id> [goal=<goal>] [template=<case template>]",
      summary: "Ask an agent to work on an object, e.g. /run CL-4" },
    { name: "runs", usage: "/runs [status]", summary: "Recent runs, e.g. /runs awaiting_review" },
    { name: "explain", usage: "/explain <run id>", summary: "What a run did and why, step by step" },
    { name: "reviews", usage: "/reviews", summary: "Decisions waiting for you" },
    { name: "proposals", usage: "/proposals", summary: "Runs the assistant proposed for you to confirm" },
    { name: "outcomes", usage: "/outcomes", summary: "What happened after decisions, and suggested rule changes" },
    { name: "clear", usage: "/clear", summary: "Clear this conversation (the engine keeps its records)" },
  ];
  const NAMES = new Set(COMMANDS.map((c) => c.name));

  // "/ask CQ-01 days=30 region=EU"  ->  {command: "ask", args: ["CQ-01"], options: {days: "30", region: "EU"}}
  function parse(text) {
    const input = String(text || "").trim();
    if (!input.startsWith("/")) return { command: null, text: input };
    const tokens = input.slice(1).match(/(?:[^\s"]+|"[^"]*")+/g) || [];
    const name = (tokens.shift() || "").toLowerCase();
    const args = [];
    const options = {};
    for (const raw of tokens) {
      const token = raw.replace(/"/g, "");
      const eq = token.indexOf("=");
      if (eq > 0) options[token.slice(0, eq)] = token.slice(eq + 1);
      else args.push(token);
    }
    return { command: name, known: NAMES.has(name), args, options };
  }

  // Values typed in a command are text; numbers and booleans are converted so questions can compare them.
  function typed(value) {
    if (/^-?\d+(\.\d+)?$/.test(value)) return Number(value);
    if (value === "true" || value === "false") return value === "true";
    return value;
  }

  function completions(prefix) {
    const p = String(prefix || "").replace(/^\//, "").toLowerCase();
    return COMMANDS.filter((c) => c.name.startsWith(p));
  }

  const STOP = new Set(("a an the of to for in on at by with is are was were be been which what who whom whose " +
    "how many much show me list all any do does did i we you it its this that these those there please can " +
    "could would give tell get find and or from about".split(" ")));

  function stem(word) {
    return word.replace(/(ing|ed|es|s)$/, "");
  }

  function words(text) {
    return String(text || "").toLowerCase().split(/[^a-z0-9_-]+/)
      .filter((w) => w && !STOP.has(w)).map(stem).filter((w) => w.length > 1);
  }

  function overlap(a, b) {
    const set = new Set(b);
    const hits = a.filter((w) => set.has(w)).length;
    return hits / Math.max(1, Math.min(a.length, b.length));
  }

  // Plain language -> ranked suggestions of commands, from the engine's own ontology (no AI involved).
  function suggest(text, ontology, limit) {
    const out = [];
    const said = words(text);
    const lower = String(text || "").toLowerCase();
    if (!ontology) return out;
    for (const q of ontology.questions || []) {
      const score = overlap(said, words(q.question));
      if (score > 0) out.push({ score, label: q.question, command: `/ask ${q.id}` });
    }
    for (const [name, e] of Object.entries(ontology.entities || {})) {
      const names = [name, ...(e.aliases || [])].map((n) => n.toLowerCase());
      if (names.some((n) => said.includes(stem(n)) || lower.includes(n))) {
        out.push({ score: 0.6, label: `List ${name} objects`, command: `/objects ${name}` });
      }
    }
    for (const [name, g] of Object.entries(ontology.goals || {})) {
      const score = overlap(said, words(`${name.replace(/_/g, " ")} ${g.description || ""}`));
      const ids = String(text || "").match(/\b[A-Z][A-Z0-9]*-\d+\b/g) || [];
      if (score > 0 && ids.length) {
        for (const id of ids) out.push({ score: score + 0.5, label: `${g.description || name} for ${id}`,
                                          command: `/run ${id} goal=${name}` });
      }
    }
    for (const id of String(text || "").match(/\b[A-Z][A-Z0-9]*-\d+\b/g) || []) {
      out.push({ score: 0.55, label: `Show ${id}`, command: `/object ${id}` });
    }
    if (/\b(review|approv|decision|waiting)/.test(lower)) {
      const mine = /\b(review|approv|decision)/.test(lower) && /\b(waiting|pending|my|me|i)\b/.test(lower);
      out.push({ score: mine ? 0.8 : 0.5, label: "Decisions waiting for you", command: "/reviews" });
    }
    if (/\b(why|explain|what happened)\b/.test(lower)) {
      const run = (String(text).match(/\b[0-9a-f]{12}\b/) || [])[0];
      if (run) out.push({ score: 0.9, label: `Explain run ${run}`, command: `/explain ${run}` });
    }
    const seen = new Set();
    return out.sort((a, b) => b.score - a.score)
      .filter((s) => (seen.has(s.command) ? false : seen.add(s.command)))
      .slice(0, limit || 4);
  }

  function isGreeting(text) {
    return /^\s*(hi|hello|hey|hiya|good (morning|afternoon|evening)|bonjour|salut|salam|marhaba|hola)\b[\s!.,?]*\w*[\s!.?]*$/i
      .test(String(text || ""));
  }

  return { COMMANDS, parse, typed, completions, suggest, words, isGreeting };
});
