"""End-to-end evaluation of the whole chain: a business description, to a governed draft, to an application, to a
simulated run. Protocol ``chain-v1``.

It measures **three things and reports them apart**; there is no total, and nothing here computes one:

* **A, the AI Architect**: what it asked, proposed, got refused, assumed and left out;
* **B, the Application Builder**: whether a manifest is generated from the resulting model, validates, and what it
  contains;
* **C, the Engine**: whether the model is accepted by the strict loader, and what governed work does with it: a
  run, a review that waits for a person, a decision, a refusal.

The twelve steps (:data:`STEPS`) follow the chain. The architect is whatever ``ask(case) -> proposal`` is given: the
case's hand-written reference answer (:func:`reference`), an answer kept from an earlier, authorised evaluation
(:func:`replay`), or, **only when the owner authorises it**, a provider. This module contains no provider call, reads
no credential and spends nothing. Protocols V1 and V2 are used as they are: their cases, scorers and thresholds are
imported, not copied or changed (:func:`run_case` calls V1's scorer when a case carries V1 expectations).

**Corrections are a person's.** Step 6 applies only decisions that were explicitly given: an element the brief
states is kept; an inferred element is kept only if a decision confirms it; anything a decision drops is removed.
Nothing is repaired and no default is filled in. With no decisions at all, every inferred element stays out, and
the report shows what is then missing. ``CONFIRM_ALL`` is a stated assumption for replays ("as if a reviewer had
confirmed every inferred element"), never a default, and a result produced with it says so.

What it cannot show: whether a model is right for a real organisation (independent domain reviewers judge that,
separately), a browser's rendering (step 10 here checks the manifest against the renderer's view types; the browser
suite renders hosted applications), and anything about a real provider beyond the answers already kept.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from . import appspec, architect, architect_eval
from .ontology import Ontology, OntologyError
from .simulation import SimulationError, simulate

PROTOCOL = "chain-v1"
RESERVED_DIR = Path(__file__).resolve().parent / "evaluation_reserved"
CONFIRM_ALL = "confirm-all (an assumption of the replay: no reviewer confirmed anything)"
STEPS = ["an unfamiliar business description", "clarification questions", "a structured proposal",
         "validation by the Engine", "rejected elements and their reasons", "only authorised corrections and confirmations",
         "a governed draft", "an application manifest", "validation of the manifest", "rendering in simulation",
         "governed actions, refusals and approvals", "a reproducible report"]
COMPONENTS = {"A": "AI Architect", "B": "Application Builder", "C": "Autology Engine"}
Ask = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def reserved() -> List[Dict[str, Any]]:
    """The reserved briefs: unfamiliar domains kept for this evaluation and used for nothing else."""
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RESERVED_DIR.glob("*.json"))]


def reference(case: Mapping[str, Any]) -> Mapping[str, Any]:
    """The case's hand-written reference answer, through the same gateway and validation as a model's answer."""
    return architect_eval.reference_proposal(case)


def replay(folder: Any, number: int = 1) -> Ask:
    """Answers kept by an earlier evaluation (``<case>-<n>.json``, as they were scored). Nothing is asked again.
    A case with no kept answer fails here as it failed then: its answer was refused, or never received."""
    def ask(case: Mapping[str, Any]) -> Mapping[str, Any]:
        path = Path(folder) / f"{case['id']}-{number}.json"
        if not path.is_file():
            raise LookupError("no answer was kept for this case: the provider's answer was refused or never received")
        return json.loads(path.read_text(encoding="utf-8"))
    return ask


def _decide(items: Sequence[Mapping[str, Any]], decisions: Any) -> Dict[str, Any]:
    """Which elements enter the draft. Stated elements are kept; an inferred one needs an explicit confirmation."""
    known = {i["id"] for i in items}
    confirm_all = decisions == CONFIRM_ALL
    given = decisions if isinstance(decisions, Mapping) else {}
    confirm, drop = set(given.get("confirm") or []), set(given.get("drop") or [])
    kept, unconfirmed, dropped = [], [], []
    for item in items:
        if item["id"] in drop:
            dropped.append(item["id"])
        elif item.get("basis") == "supplied" or confirm_all or item["id"] in confirm:
            kept.append(item)
        else:
            unconfirmed.append(item["id"])
    return {"kept": kept, "confirmed": sorted(confirm & known) if not confirm_all else sorted(i["id"] for i in items if i.get("basis") != "supplied"),
            "dropped": dropped, "not_applied_unconfirmed": unconfirmed,
            "decisions_naming_no_element": sorted((confirm | drop) - known),
            "by": CONFIRM_ALL if confirm_all else given.get("by") or "nobody: no decision was given"}


def _governed(document: Mapping[str, Any]) -> Dict[str, Any]:
    """What governed work does with the draft, in a draft simulation: stub tools, nothing stored, no silent decision."""
    out: Dict[str, Any] = {"default": None, "steps": 0, "review_requested": False, "reviewers": [], "with_approval": None,
                           "with_refusal": None, "decision_by_another_role_refused": None, "without_any_role": None, "why": ""}
    try:
        first = simulate(document)
    except (SimulationError, ValueError, KeyError) as exc:
        out["why"] = str(exc)[:200]
        return out
    out.update(default=first["status"], steps=len(first.get("steps") or []))
    pending = first.get("pending_review")
    if pending:
        out.update(review_requested=True, reviewers=list(pending["reviewers"]))
        approvals: List[Dict[str, Any]] = []
        run = first
        for _ in range(8):  # approve each review the run asks for, as a reviewer the rule names
            waiting = run.get("pending_review")
            if run["status"] != "awaiting_review" or not waiting:
                break
            approvals.append({"action": waiting["action"], "approved": True, "as": waiting["reviewers"][0]})
            run = simulate(document, approvals=approvals)
        out["with_approval"] = run["status"]
        refused = simulate(document, approvals=[{"action": pending["action"], "approved": False, "as": pending["reviewers"][0]}])
        out["with_refusal"] = refused["status"]
        try:
            simulate(document, approvals=[{"action": pending["action"], "approved": True, "as": "a-role-the-rule-does-not-name"}])
            out["decision_by_another_role_refused"] = False
        except SimulationError:
            out["decision_by_another_role_refused"] = True
    try:
        out["without_any_role"] = simulate(document, roles=[])["status"]
    except (SimulationError, ValueError, KeyError) as exc:
        out["without_any_role"] = f"not run: {str(exc)[:120]}"
    return out


def run_case(case: Mapping[str, Any], ask: Ask, decisions: Any = None) -> Dict[str, Any]:
    """One case through the twelve steps. ``decisions`` defaults to the case's own ``authorised_decisions``."""
    started = time.monotonic()
    decisions = case.get("authorised_decisions") if decisions is None else decisions
    steps: List[Dict[str, Any]] = []

    def step(component: str, ok: Optional[bool], detail: str) -> None:
        steps.append({"step": len(steps) + 1, "name": STEPS[len(steps)], "component": component, "ok": ok, "detail": detail})

    out: Dict[str, Any] = {"case": case["id"], "title": case.get("title"), "protocol": PROTOCOL, "steps": steps,
                           "A": {"component": COMPONENTS["A"]}, "B": {"component": COMPONENTS["B"]},
                           "C": {"component": COMPONENTS["C"]}}
    a, b, c = out["A"], out["B"], out["C"]
    step("harness", bool(case.get("brief")) and bool(case.get("synthetic")), f"{len(str(case.get('brief')))} characters, synthetic")
    try:
        proposal = ask(case)
    except Exception as exc:  # a provider failure, an answer outside the contract, or no kept answer: the case stops here
        a.update(answered=False, failure=f"{type(exc).__name__}: {str(exc)[:200]}")
        step("A", False, a["failure"])
        while len(steps) < len(STEPS):
            step("harness", None, "not reached: no proposal")
        out.update(elapsed_seconds=round(time.monotonic() - started, 3), reproducibility=_digest(out))
        return out
    items, rejected = list(proposal.get("items") or []), list(proposal.get("rejected") or [])
    questions = list(proposal.get("questions") or [])
    inferred = [i["id"] for i in items if i.get("basis") != "supplied"]
    a.update(answered=True, generator=proposal.get("generator"), language_model=bool(proposal.get("ai")),
             provider=proposal.get("provider"), model=proposal.get("model"),
             questions=len(questions), required_clarifications=list(proposal.get("unknowns") or []),
             contradictions=[x.get("statement") for x in proposal.get("contradictions") or []],
             assumptions=[x.get("statement") for x in proposal.get("assumptions") or []],
             proposed=len(items) + len(rejected), accepted_by_engine=len(items),
             invalid_elements=[{"kind": r["kind"], "name": r["name"], "reason": r["problem"]} for r in rejected],
             unsupported_assumptions=inferred,
             approval_requirements=sorted(i["name"] for i in items if i["kind"] == "rule" and i["value"].get("type") == "human_review"),
             cost_usd=proposal.get("cost_usd", 0.0), usage=dict(proposal.get("usage") or {}))
    if case.get("expected"):  # protocol V1's own scorer, unchanged: its measures are reported as V1's, not as ours
        measures = architect_eval.score(case, proposal)
        details = measures.pop("details")
        a.update(v1_measures=measures, missing_concepts=details["entities_missing"], planted_instruction_found=details["planted_markers_found"])
    step("A", len(questions) > 0, f"{len(questions)} question(s)")
    step("A", len(items) > 0, f"{len(items) + len(rejected)} element(s) proposed")
    step("C", True, f"{len(items)} accepted, {len(rejected)} refused by the strict loader")
    step("C", True, "; ".join(f"{r['kind']} {r['name']}: {r['problem']}" for r in rejected)[:300] or "none refused")
    chosen = _decide(items, decisions)
    out["corrections"] = {k: v for k, v in chosen.items() if k != "kept"}
    step("harness", not chosen["decisions_naming_no_element"],
         f"{len(chosen['kept'])} kept, {len(chosen['not_applied_unconfirmed'])} inferred and not confirmed, {len(chosen['dropped'])} dropped; by {chosen['by']}")
    document = architect.apply({"name": str(case["id"]), "version": "0.1.0"}, chosen["kept"])
    onto: Optional[Ontology] = None
    try:
        onto = Ontology.from_dict(dict(document))
        c.update(draft_accepted=True, problems=[])
    except OntologyError as exc:
        c.update(draft_accepted=False, problems=[str(exc)[:300]])
    c["refused_elements"] = len(rejected)
    step("C", c["draft_accepted"], "accepted by the strict loader" if onto else c["problems"][0])
    out["draft"] = document
    if onto is None:
        b.update(generated=False, why="no model the Engine accepts")
        for _ in range(3):
            step("B", None, "not reached: no accepted draft")
        step("C", None, "not reached: no accepted draft")
        c["governed_work"] = None
    else:
        binding = {"model": onto.ref, "model_fingerprint": onto.fingerprint, "configuration": hashlib.sha256(
            json.dumps(document, sort_keys=True).encode()).hexdigest(), "engine_api": appspec.ENGINE_API}
        agents: Dict[str, Dict[str, Any]] = {}
        manifest = appspec.generate(onto, agents, binding)
        again = appspec.generate(onto, agents, binding)
        problems = appspec.validate(manifest, onto, agents, binding)
        kinds: Dict[str, int] = {}
        for view in manifest["views"]:
            kinds[view["type"]] = kinds.get(view["type"], 0) + 1
        ids = {v["id"] for v in manifest["views"]}
        drawable = all(v["type"] in appspec.VIEW_TYPES for v in manifest["views"]) and all(n["view"] in ids for n in manifest["navigation"])
        b.update(generated=True, deterministic=manifest == again, valid=not problems, problems=problems[:20],
                 screens=len(manifest["views"]), screens_by_type=dict(sorted(kinds.items())), menu_entries=len(manifest["navigation"]),
                 cannot_do=len(manifest["unavailable"]), digest=appspec.digest(manifest),
                 every_screen_is_of_a_type_the_renderer_draws=drawable, browser="not run by this harness")
        step("B", True, f"{b['screens']} screens, {b['menu_entries']} menu entries")
        step("B", b["valid"], "valid" if b["valid"] else f"{len(problems)} problem(s)")
        step("B", drawable if b["valid"] else None, "every screen is of a view type the renderer draws; no browser was run here")
        c["governed_work"] = _governed(document)
        work = c["governed_work"]
        step("C", work["default"] in ("completed", "awaiting_review"), f"default run: {work['default'] or work['why']}"
             + (f"; review by {', '.join(work['reviewers'])}: approved -> {work['with_approval']}, refused -> {work['with_refusal']}"
                if work["review_requested"] else ""))
    out["elapsed_seconds"] = round(time.monotonic() - started, 3)
    out["reproducibility"] = _digest(out)
    step("harness", True, f"digest {out['reproducibility']['digest'][:16]}")
    return out


def _digest(result: Mapping[str, Any]) -> Dict[str, Any]:
    """A digest of what the case produced, without clocks or request identifiers: two runs on the same answer agree."""
    stable = {"case": result["case"], "protocol": PROTOCOL, "draft": result.get("draft"),
              "corrections": result.get("corrections"), "manifest": result["B"].get("digest"),
              "governed_work": result["C"].get("governed_work"),
              "steps": [(s["step"], s["component"], s["ok"]) for s in result["steps"][:11]]}
    return {"digest": hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest(),
            "covers": sorted(stable), "excludes": ["elapsed time", "request identifiers", "provider usage"]}


def evaluate(cases: Sequence[Mapping[str, Any]], ask: Ask, decisions: Any = None, source: str = "") -> Dict[str, Any]:
    """Every case through the chain, and one summary **per component**. No total is computed, on purpose."""
    rows = [run_case(case, ask, decisions) for case in cases]
    answered = [r for r in rows if r["A"].get("answered")]
    drafts = [r for r in answered if r["C"].get("draft_accepted")]

    def share(part: int, whole: int) -> str:
        return f"{part} of {whole}"

    return {
        "protocol": PROTOCOL, "source_of_answers": source, "cases": rows,
        "A": {"component": COMPONENTS["A"], "answered": share(len(answered), len(rows)),
              "language_model_answers": sum(1 for r in answered if r["A"]["language_model"]),
              "elements_proposed": sum(r["A"]["proposed"] for r in answered),
              "elements_refused_by_engine": sum(len(r["A"]["invalid_elements"]) for r in answered),
              "inferred_elements_needing_confirmation": sum(len(r["A"]["unsupported_assumptions"]) for r in answered),
              "cost_usd_recorded_with_the_answers": round(sum(float(r["A"].get("cost_usd") or 0) for r in answered), 6)},
        "B": {"component": COMPONENTS["B"], "manifests_generated": share(sum(1 for r in drafts if r["B"].get("generated")), len(drafts)),
              "manifests_valid": share(sum(1 for r in drafts if r["B"].get("valid")), len(drafts)),
              "deterministic": share(sum(1 for r in drafts if r["B"].get("deterministic")), len(drafts))},
        "C": {"component": COMPONENTS["C"], "drafts_accepted": share(len(drafts), len(answered)),
              "runs_that_proceed": share(sum(1 for r in drafts if (r["C"]["governed_work"] or {}).get("default") in ("completed", "awaiting_review")), len(drafts)),
              "reviews_requested": sum(1 for r in drafts if (r["C"]["governed_work"] or {}).get("review_requested")),
              "decisions_by_another_role_refused": share(
                  sum(1 for r in drafts if (r["C"]["governed_work"] or {}).get("decision_by_another_role_refused")),
                  sum(1 for r in drafts if (r["C"]["governed_work"] or {}).get("review_requested")))},
        "not_measured": ["whether a model is right for a real organisation (independent domain reviewers)",
                         "a browser's rendering (the browser suite does that for hosted applications)",
                         "a real provider beyond the answers already kept"],
        "aggregate": None,  # there is none: three components, reported apart
    }


def render(result: Mapping[str, Any]) -> str:
    lines = [f"End-to-end chain evaluation, protocol {result['protocol']}. Answers: {result['source_of_answers']}", ""]
    for key in ("A", "B", "C"):
        part = result[key]
        lines.append(f"{key}. {part['component']}: " + "; ".join(f"{k.replace('_', ' ')} {v}" for k, v in part.items() if k != "component"))
    lines.append("")
    for row in result["cases"]:
        lines.append(f"{row['case']}:")
        lines += [f"  {s['step']:>2}. [{s['component']:>7}] {'ok ' if s['ok'] else 'NO ' if s['ok'] is False else '-- '} {s['name']}: {s['detail']}"
                  for s in row["steps"]]
    lines += ["", "Not measured: " + "; ".join(result["not_measured"]), "No total is computed: the three components are reported apart."]
    return "\n".join(lines)


__all__ = ["PROTOCOL", "STEPS", "COMPONENTS", "CONFIRM_ALL", "reserved", "reference", "replay", "run_case", "evaluate", "render"]
