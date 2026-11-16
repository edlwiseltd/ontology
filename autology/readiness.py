"""Release readiness of a use case: mandatory gates (REL-2) and an evidence-based scorecard (REL-3).

Two things are computed from the same list of **conditions**, each of which is measured on the running use case
and names its own evidence:

* **Gates.** A condition can be *mandatory* for a target stage (``pilot``, ``production``). A mandatory condition
  that does not hold, or that cannot be verified because its evidence is missing, is a **blocker**: promotion to
  that stage is refused on the server, whatever the score. A missing proof is never counted as a pass.
* **Scorecard.** Each of six dimensions (ontology validity, data and knowledge quality, permission and security
  integrity, agent and action readiness, simulation and test evidence, operational and audit readiness) gets a
  score: the mean of its measured conditions (``held / total`` for each, equally counted), from 0 to 100. Every
  dimension shows its calculation, the evidence it used, the evidence that is missing, its blockers and the
  corrective actions. The overall score is the weighted mean of the dimensions that could be measured.

The score informs; it decides nothing. ``promotion.allowed`` depends on the blockers only, so a high score never
overrides a mandatory condition. ``production`` is refused in this release whatever the gates say (owner decision
PROD): the report states whether the conditions would hold and that the stage is not authorised.

**Weights are a proposal.** :data:`PROPOSED_WEIGHTS` awaits the owner's approval (decision D26). A use case's
configuration can set other weights (``"readiness": {"weights": {...}}``); they change the overall figure only and
are always reported with their status.

The conditions reuse the engine's own checks rather than restating them: the stage checks of
:mod:`autology.lifecycle`, the linter, the integrity rules. The platform supplies what only it knows (the stage
history, the active release, the access review) through ``context``; evidence nobody supplied is reported missing.

Extension point: a condition is a plain :class:`Condition`. A future sector pack or plugin could contribute
conditions, but only the engine evaluates them and only the engine decides promotion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .integrity import decision_fields
from .lifecycle import REFUSED_STAGES, Check, evaluate, policy_for
from .lint import lint

DIMENSIONS: Dict[str, str] = {
    "ontology": "Ontology validity",
    "data": "Data and knowledge quality",
    "security": "Permission and security integrity",
    "agents": "Agent and action readiness",
    "evidence": "Simulation and test evidence",
    "operations": "Operational and audit readiness",
}
PROPOSED_WEIGHTS: Dict[str, float] = {"ontology": 15, "data": 15, "security": 20, "agents": 15, "evidence": 20,
                                      "operations": 15}
WEIGHTS_STATUS = "proposed: not approved by the owner (decision D26)"
TARGETS = ("pilot", "production")
BOTH: Tuple[str, ...] = ("pilot", "production")
PRODUCTION: Tuple[str, ...] = ("production",)


@dataclass
class Condition:
    id: str
    dimension: str
    title: str
    held: Optional[int]  # how many of ``total`` satisfy the condition; None: could not be measured
    total: int
    detail: str  # what was found, in words
    mandatory_for: Tuple[str, ...] = ()  # stages whose promotion this condition can block
    evidence: List[str] = field(default_factory=list)  # what the measurement rests on
    missing: Optional[str] = None  # the evidence that would be needed (when not measured)
    action: str = ""  # what to do when it does not hold
    applicable: bool = True  # False: nothing to measure here (e.g. no pipeline): neither scored nor blocking

    def __post_init__(self) -> None:
        if self.total <= 0:  # nothing to count (an empty model has no entity to relate): not a condition here
            self.applicable = False

    @property
    def measured(self) -> bool:
        return self.applicable and self.held is not None

    @property
    def passed(self) -> Optional[bool]:
        return None if not self.measured else self.held == self.total

    def blocks(self, target: str) -> bool:
        return self.applicable and target in self.mandatory_for and self.passed is not True

    def to_dict(self, target: str) -> Dict[str, Any]:
        return {"id": self.id, "dimension": self.dimension, "title": self.title, "applicable": self.applicable,
                "measured": self.measured, "passed": self.passed, "held": self.held, "total": self.total,
                "detail": self.detail, "evidence": list(self.evidence), "missing_evidence": self.missing,
                "mandatory_for": list(self.mandatory_for), "blocking": self.blocks(target),
                "action": "" if self.passed or not self.applicable else self.action}


def _yes(ok: bool) -> int:
    return 1 if ok else 0


# what the existing stage checks (autology.lifecycle, and the platform's release check) mean here
STAGE_CHECKS: Dict[str, Tuple[str, str, str]] = {
    "configuration_valid": ("ontology", "The model loads under the strict schema", "Fix the model until it validates"),
    "audit_key": ("security", "Audit chains are signed with the workspace's key",
                  "Start the platform with an audit key"),
    "no_quarantined_records": ("data", "Every stored record validates against the model",
                               "Correct or remove the quarantined records"),
    "engine_simulation_mode_off": ("evidence", "The engine's simulation mode (automatic approvals) is off",
                                   "Turn the engine's simulation mode off before a pilot"),
    "reviewers_assigned": ("security", "Every reviewer role the rules require is held by a named member",
                           "Grant each missing reviewer role to a person"),
    "audit_chains_verify": ("operations", "Every run's audit chain verifies",
                            "Investigate the runs whose audit chain does not verify"),
    "external_calls_reconciled": ("operations", "No external call is waiting for reconciliation",
                                  "Reconcile the external calls whose outcome is unknown"),
    "simulated_run_completed": ("evidence", "A run completed since the use case entered simulation",
                                "Run the use case to completion in simulation"),
    "configuration_unchanged_since_simulation": ("evidence", "The configuration is the one that was simulated",
                                                 "Simulate the current configuration again"),
    "approved_release_active": ("operations", "An independently approved release is active and is what runs",
                                "Propose a release, have another person approve it, activate it"),
}


def _from_check(check: Check) -> Condition:
    dimension, title, action = STAGE_CHECKS.get(check.id, ("operations", check.id, "Resolve this check"))
    return Condition(check.id, dimension, title, _yes(check.passed), 1, check.detail, BOTH, [check.detail], None,
                     action)


def conditions(service: Any, context: Optional[Mapping[str, Any]] = None) -> List[Condition]:
    """Every readiness condition of ``service``, measured now. ``context`` is what the platform knows:
    ``entered_simulation`` (the stage event), ``release_checks`` (:class:`autology.lifecycle.Check` list),
    ``unrestricted_needing_review`` (a count), ``recovery`` (evidence of a verified backup, or None)."""
    context = dict(context or {})
    onto = service.ontology
    out = [_from_check(c) for c in evaluate("pilot", service, context.get("entered_simulation"))]
    if "release_checks" in context:
        out += [_from_check(c) for c in context["release_checks"]]
    else:
        out.append(Condition("approved_release_active", "operations", STAGE_CHECKS["approved_release_active"][1],
                             None, 1, "not known to this engine", BOTH, [],
                             "the platform's release registry (a standalone engine has none)",
                             STAGE_CHECKS["approved_release_active"][2]))

    # -- ontology validity ---------------------------------------------------------------------------------
    tools = [t for cfg in service.agents.values() for member in [cfg.agent] + list(cfg.agent.delegates)
             for t in member.tools]
    findings = lint(onto)
    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warning"]
    out.append(Condition("lint_no_errors", "ontology", "The linter reports no error", _yes(not errors), 1,
                         f"{len(errors)} errors, {len(warnings)} warnings", BOTH,
                         [f"{f.code}: {f.message}" for f in errors + warnings][:10], None,
                         "Fix the linter's errors (autology lint)"))
    out.append(Condition("goals_defined", "ontology", "At least one goal says what the agents pursue",
                         _yes(bool(onto.goals)), 1, f"{len(onto.goals)} goals", BOTH, sorted(onto.goals)[:10], None,
                         "Define a goal: without one no run can be planned"))
    linked = {r.source for r in onto.relationships} | {r.target for r in onto.relationships}
    isolated = sorted(set(onto.entities) - linked) if len(onto.entities) > 1 else []
    out.append(Condition("entities_related", "ontology", "Every entity is related to the rest of the model",
                         len(onto.entities) - len(isolated), len(onto.entities),
                         f"isolated: {', '.join(isolated)}" if isolated else "no isolated entity", (), isolated, None,
                         "Relate each isolated entity, or remove it"))

    # -- data and knowledge quality ------------------------------------------------------------------------
    used = decision_fields(onto, getattr(service, "automations", None))
    guarded = {r.params["field"] for r in onto.rules_of("write_access")}
    unprotected = sorted(set(used) - guarded)
    out.append(Condition("decision_facts_protected", "data",
                         "Every fact that rules, preconditions or goals read has a named writer",
                         len(used) - len(unprotected), len(used),
                         f"no write_access rule on: {', '.join(unprotected)}" if unprotected else
                         "every decision fact has a write_access rule", PRODUCTION, unprotected[:10], None,
                         "Add a write_access rule for each fact decisions rest on (and classify it "
                         "decision_critical)", applicable=bool(used)))
    critical = sorted(onto.critical_fields)
    unruled = [ref for ref in critical if ref not in guarded]
    out.append(Condition("critical_facts_have_a_writer", "data",
                         "Every fact classified decision-critical has a rule naming who may change it",
                         len(critical) - len(unruled), len(critical),
                         f"nobody can change: {', '.join(unruled)}" if unruled else "each has a write_access rule",
                         BOTH, unruled, None, "Add a write_access rule naming the roles that maintain the fact",
                         applicable=bool(critical)))
    pipelines = sorted(getattr(service, "pipelines", {}) or {})
    failed = []
    for name in pipelines:
        batches = service.store.ingest_batches(name, limit=1)
        if batches and batches[0].get("status") == "failed":
            failed.append(name)
    out.append(Condition("pipelines_last_load_succeeded", "data", "The last load of every pipeline succeeded",
                         len(pipelines) - len(failed), len(pipelines),
                         f"last load failed: {', '.join(failed)}" if failed else "no pipeline's last load failed",
                         PRODUCTION, failed, None, "Fix the failing source and run the pipeline again",
                         applicable=bool(pipelines)))

    # -- permission and security integrity -----------------------------------------------------------------
    readable = {r.params["field"] for r in onto.rules_of("data_access")}
    sensitive = sorted(f"{e.name}.{a.name}" for e in onto.entities.values() for a in e.attributes.values()
                       if a.sensitivity in ("pii", "confidential"))
    exposed = [ref for ref in sensitive if ref not in readable]
    out.append(Condition("sensitive_fields_guarded", "security",
                         "Every personal or confidential field has a rule saying who may read it",
                         len(sensitive) - len(exposed), len(sensitive),
                         f"no data_access rule on: {', '.join(exposed)}" if exposed else "each has a data_access rule",
                         PRODUCTION, exposed, None, "Add a data_access rule for each sensitive field",
                         applicable=bool(sensitive)))
    discretion = list(getattr(service, "model_findings", []) or [])
    out.append(Condition("model_discretion_reviewed", "security",
                         "No language model may choose a consequential action that nobody reviews",
                         _yes(not discretion), 1, "; ".join(discretion) or "no unreviewed model discretion", BOTH,
                         discretion, None, "Put the action under human review, or remove it from model_may_choose"))
    pending = context.get("unrestricted_needing_review")
    out.append(Condition("unrestricted_grants_reviewed", "security",
                         "Every unrestricted grant has been confirmed by a person who is not its holder",
                         None if pending is None else _yes(pending == 0), 1,
                         "not known to this engine" if pending is None else f"{pending} grants await review",
                         PRODUCTION, [], "the platform's access review" if pending is None else None,
                         "Confirm, narrow or revoke each unrestricted grant in the access review"))

    # -- agent and action readiness ------------------------------------------------------------------------
    capabilities = {t.capability for t in tools}
    actions = sorted(onto.actions)
    untooled = [a for a in actions if onto.actions[a].capability not in capabilities]
    out.append(Condition("actions_have_a_tool", "agents", "Every action has a tool that performs it",
                         len(actions) - len(untooled), len(actions),
                         f"no tool for: {', '.join(untooled)}" if untooled else "every action has a tool", BOTH,
                         untooled[:10], None, "Give an agent a tool for the capability, or remove the action",
                         applicable=bool(actions)))
    suspended = sorted(name for name, cfg in service.agents.items()
                       if cfg.agent.principal.name in cfg.agent.governance.suspended)
    out.append(Condition("no_agent_suspended", "agents", "No agent is suspended",
                         len(service.agents) - len(suspended), len(service.agents),
                         f"suspended: {', '.join(suspended)}" if suspended else "no agent is suspended", BOTH,
                         suspended, None, "Review why the agent was suspended before reinstating it",
                         applicable=bool(service.agents)))
    declared = service.ontology.source.get("actions") or {}
    undeclared = [a for a in actions if "side_effect" not in (declared.get(a) or {})]
    out.append(Condition("side_effects_declared", "agents",
                         "Every action declares what repeating it does outside Autology",
                         len(actions) - len(undeclared), len(actions),
                         f"undeclared (treated as unsafe to repeat): {', '.join(undeclared)}" if undeclared else
                         "every action declares its side effect", PRODUCTION, undeclared[:10], None,
                         "Declare side_effect (none, idempotent or non_idempotent) on each action",
                         applicable=bool(actions)))
    allowed = set(policy_for("pilot")["environments"])
    by_capability: Dict[str, set] = {}
    for tool in tools:
        by_capability.setdefault(tool.capability, set()).add(tool.environment)
    untestable = [a for a in actions if by_capability.get(onto.actions[a].capability)
                  and not by_capability[onto.actions[a].capability] & allowed]
    tooled = [a for a in actions if a not in untooled]
    out.append(Condition("actions_testable_before_production", "agents",
                         "Every action has a simulated or sandbox tool, so it can be exercised before production",
                         len(tooled) - len(untestable), len(tooled),
                         f"only production tools for: {', '.join(untestable)}" if untestable else
                         "every action can be exercised without a production system", BOTH, untestable, None,
                         "Provide a simulated or sandbox tool for the action", applicable=bool(tooled)))

    # -- simulation and test evidence ----------------------------------------------------------------------
    since = (context.get("entered_simulation") or {}).get("at")
    runs = [r for r in service.store.list_runs("completed", limit=10 ** 9)
            if r["ontology"] == onto.ref and (since is None or r["created_at"] >= since)]
    exercised: set = set()
    for row in runs[:200]:
        exercised |= {e.data.get("action") for e in service.store.load_run(row["run_id"]).audit
                      if e.event == "step"}
    never = [a for a in actions if a not in exercised]
    out.append(Condition("actions_exercised", "evidence",
                         "Every action was performed in a completed run of this model",
                         len(actions) - len(never), len(actions),
                         f"never performed: {', '.join(never)}" if never else "every action was performed", PRODUCTION,
                         [f"{len(runs)} completed runs of {onto.ref}"], None,
                         "Run cases that reach each action (simulation or pilot)", applicable=bool(actions)))
    reviewed = sorted({str(r.params["action"]) for r in onto.rules_of("human_review")})
    decided = {r["action"] for r in service.store.list_reviews(None, limit=10 ** 6)
               if r["status"] in ("approved", "rejected")}
    undecided = [a for a in reviewed if a not in decided]
    out.append(Condition("review_paths_exercised", "evidence",
                         "Every action under human review was decided by a person at least once",
                         len(reviewed) - len(undecided), len(reviewed),
                         f"never decided: {', '.join(undecided)}" if undecided else "each review path was exercised",
                         PRODUCTION, [f"{len(decided)} reviewed actions with a recorded decision"], None,
                         "Run a case to each review and have its reviewer decide it", applicable=bool(reviewed)))

    # -- operational and audit readiness -------------------------------------------------------------------
    conflicts = [run_id for run_id in service.store.pending_write_backs()
                 if (service.store.run_sources(run_id) or {}).get("conflicts")]
    out.append(Condition("no_write_back_conflict", "operations", "No run is waiting on a write-back conflict",
                         _yes(not conflicts), 1,
                         f"{len(conflicts)} runs wait for a person to resolve a conflict" if conflicts else
                         "no write-back conflict is pending", BOTH, conflicts[:10], None,
                         "Resolve the conflicting values, then retry the write-back"))
    recovery = context.get("recovery")
    out.append(Condition("recovery_evidence", "operations", "A verified backup exists and a restore was rehearsed",
                         None if not recovery else _yes(bool(recovery.get("verified"))), 1,
                         "no recovery evidence is recorded for this use case" if not recovery else
                         str(recovery.get("detail") or "recorded"), PRODUCTION,
                         list((recovery or {}).get("evidence") or []),
                         None if recovery else "a recorded platform backup verification and restore drill",
                         "Take a platform backup, verify it, rehearse a restore, and record the result"))
    return out


def weights_of(service: Any) -> Tuple[Dict[str, float], str]:
    """The weights in force and their status. Configured weights replace the proposal; neither is ratified here."""
    configured = (getattr(service, "readiness", None) or {}).get("weights")
    if not configured:
        return dict(PROPOSED_WEIGHTS), WEIGHTS_STATUS
    return {d: float(configured[d]) for d in DIMENSIONS}, "configured for this use case; " + WEIGHTS_STATUS


def checked_weights(spec: Any) -> Any:
    """``spec`` (a use case's ``readiness`` configuration) if it is six non-negative weights with a positive sum;
    ValueError otherwise."""
    if spec is None:
        return None
    weights = spec.get("weights") if isinstance(spec, Mapping) else None
    if not isinstance(spec, Mapping) or set(spec) - {"weights"} or not isinstance(weights, Mapping) \
            or set(weights) != set(DIMENSIONS):
        raise ValueError(f"readiness: {{\"weights\": {{...}}}} with exactly the dimensions {sorted(DIMENSIONS)}")
    values = list(weights.values())
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 for v in values) or sum(values) <= 0:
        raise ValueError("readiness.weights: non-negative numbers with a positive sum")
    return spec


def report(service: Any, target: str = "pilot", context: Optional[Mapping[str, Any]] = None,
           found: Optional[Sequence[Condition]] = None) -> Dict[str, Any]:
    """The readiness report for promoting ``service`` to ``target``: gates, scorecard, and what to do next."""
    if target not in TARGETS:
        raise ValueError(f"target must be one of {', '.join(TARGETS)}")
    found = list(found) if found is not None else conditions(service, context)
    weights, status = weights_of(service)
    dimensions, weighted, used_weight = [], 0.0, 0.0
    for key, title in DIMENSIONS.items():
        mine = [c for c in found if c.dimension == key]
        measured = [c for c in mine if c.measured]
        score = round(100 * sum((c.held or 0) / c.total for c in measured) / len(measured), 1) if measured else None
        if score is not None:
            weighted += score * weights[key]
            used_weight += weights[key]
        terms = " + ".join(f"{c.held}/{c.total}" for c in measured)
        dimensions.append({
            "id": key, "title": title, "score": score, "weight": weights[key],
            "calculation": (f"100 x ({terms}) / {len(measured)} measured conditions = {score}" if measured else
                            "no condition of this dimension could be measured"),
            "conditions": [c.to_dict(target) for c in mine],
            "evidence": [e for c in measured for e in c.evidence][:20],
            "missing_evidence": [f"{c.title}: {c.missing or 'not measured'}" for c in mine
                                 if c.applicable and not c.measured],
            "blocking": [c.id for c in mine if c.blocks(target)],
            "actions": [c.action for c in mine if c.applicable and c.passed is not True and c.action]})
    blockers = [{"id": c.id, "dimension": c.dimension, "title": c.title, "detail": c.detail,
                 "reason": "not verified: " + (c.missing or "evidence missing") if not c.measured else "does not hold",
                 "action": c.action} for c in found if c.blocks(target)]
    overall = round(weighted / used_weight, 1) if used_weight else None
    refused = REFUSED_STAGES.get(target)
    allowed = not blockers and not refused
    if blockers:
        why = f"{len(blockers)} mandatory conditions do not hold or cannot be verified; the score does not change that"
    elif refused:
        why = f"every mandatory condition holds, but {refused}"
    else:
        why = "every mandatory condition holds"
    return {"target": target, "generated_at": datetime.now(timezone.utc).isoformat(),
            "configuration": {"ontology": service.ontology.ref, "fingerprint": service.ontology.fingerprint},
            "gates": {"passed": not blockers, "evaluated": sum(1 for c in found if c.applicable and target in c.mandatory_for),
                      "blockers": blockers},
            "score": {"overall": overall, "weights": weights, "weights_status": status,
                      "calculation": "weighted mean of the dimensions that could be measured: "
                                     + " + ".join(f"{d['score']} x {d['weight']}" for d in dimensions
                                                  if d["score"] is not None)
                                     + (f", divided by {used_weight:g} = {overall}" if used_weight else ""),
                      "note": "the score informs; promotion depends on the gates only"},
            "dimensions": dimensions,
            "promotion": {"allowed": allowed, "reason": why},
            "production": {"authorised": False, "reason": REFUSED_STAGES["production"]}}


def _standing(condition: Mapping[str, Any]) -> str:
    if not condition["applicable"]:
        return "not applicable"
    if not condition["measured"]:
        return "not verified"
    return "holds" if condition["passed"] else "does not hold"


def differences(active: Mapping[str, Any], other: Mapping[str, Any]) -> Dict[str, Any]:
    """What differs between two reports of this module (what runs, and another configuration of the same use
    case): each condition whose standing is not the same, and each dimension's two scores. Nothing is
    recalculated: both reports were computed by :func:`report`."""
    def flat(rep: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {c["id"]: c for d in rep["dimensions"] for c in d["conditions"]}

    now, then = flat(active), flat(other)
    changed = [{"id": key, "dimension": c["dimension"], "title": c["title"],
                "active": _standing(now[key]) if key in now else "not evaluated", "subject": _standing(c),
                "detail": c["detail"], "blocking": c["blocking"]}
               for key, c in then.items() if key not in now or _standing(now[key]) != _standing(c)]
    scores = {d["id"]: d["score"] for d in active["dimensions"]}
    return {"differences": changed,
            "dimensions": [{"id": d["id"], "title": d["title"], "active": scores.get(d["id"]), "subject": d["score"]}
                           for d in other["dimensions"]]}


def gate_checks(service: Any, target: str, context: Optional[Mapping[str, Any]] = None,
                skip: Sequence[str] = ()) -> List[Check]:
    """The mandatory conditions of ``target`` as stage checks, for the promotion itself (those in ``skip`` are
    evaluated by the caller already)."""
    return [Check(c.id, c.passed is True, c.detail if c.measured else f"not verified: {c.missing or c.detail}")
            for c in conditions(service, context) if c.applicable and target in c.mandatory_for and c.id not in skip]
