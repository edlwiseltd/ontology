"""Automations: start governed runs and send notifications when the knowledge graph changes.

An automation watches one entity type and fires for each instance whose ``when`` condition holds::

    "automations": {
      "ship_signed_contracts": {
        "description": "Fulfil a contract as soon as it is signed",
        "entity": "Contract",
        "when": "Contract.status == 'signed'",
        "trigger": "change",                        # or {"every": 3600}
        "run": {"agent": "fulfilment", "goal": "fulfil_contract", "case_template": "contract_case"},
        "notify": {"roles": ["logistics_manager"], "message": "Contract {id} is signed: fulfilment started"}
      }
    }

* ``"trigger": "change"`` (default) fires when the condition *becomes* true for an instance: on a
  write through the API, on a run's write-back, or on a scheduled tick (conditions may use
  ``Params.now``, the current time in epoch seconds, so "becomes true" also covers deadlines).
  It fires once, and again only after the condition has been false in between. This state is
  persisted, so a restart does not fire everything again.
* ``"trigger": {"every": seconds}`` fires on ticks for every instance where the condition holds,
  at most once per interval per instance.
* ``run`` starts an agent run on a case assembled from the graph with a case template (see
  ``case_templates`` in the ontology). With ``"write_back": true`` (default) the run's resulting
  state is written back to the instances the case came from. The run is governed exactly like
  one started by a person: rules, reviews and audit all apply.
* ``notify`` records a notification for people holding one of ``roles``; ``{id}`` and ``{attribute}``
  placeholders take the instance's values. Webhooks configured on the server deliver notifications
  to chat or incident tools.

Automations are deployment configuration (they name agents), so they live in the server config,
validated against the ontology.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from .expressions import Expression, ExpressionError, compile_expression
from .graph import Instance
from .ontology import ID, PARAMS, Ontology, OntologyError

PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
MAX_FIRINGS_PER_PASS = 200  # guards against automations that keep re-triggering each other


@dataclass(frozen=True)
class Automation:
    name: str
    entity: str
    when: Optional[Expression]
    every: Optional[float] = None  # None: fire on change
    run: Optional[Mapping[str, Any]] = None
    notify: Optional[Mapping[str, Any]] = None
    description: str = ""
    retry_seconds: float = 300.0  # wait before retrying a firing that errored
    max_retries: int = 5  # attempts in all before giving up on an instance

    @property
    def trigger(self) -> str:
        return "change" if self.every is None else f"every {self.every:g}s"

    def holds(self, inst: Instance, now: float) -> bool:
        if inst.type != self.entity:
            return False
        if self.when is None:
            return True

        def resolve(entity: str, attr: str) -> Any:
            if entity == PARAMS:
                return now if attr == "now" else None
            return inst.get(attr)

        try:
            return bool(self.when.evaluate(resolve))
        except (ExpressionError, TypeError):
            return False  # e.g. comparing a missing value: the condition does not hold yet

    def message(self, inst: Instance) -> str:
        template = str((self.notify or {}).get("message") or f"{self.name}: {inst.type} {{id}}")
        return PLACEHOLDER.sub(lambda m: str(inst.id if m.group(1) == ID else inst.get(m.group(1))), template)

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description, "entity": self.entity,
                "when": str(self.when) if self.when else None, "trigger": self.trigger,
                "run": dict(self.run) if self.run else None, "notify": dict(self.notify) if self.notify else None}


def load_automations(specs: Mapping[str, Any], ontology: Ontology,
                     agent_goals: Mapping[str, Sequence[str]]) -> Dict[str, Automation]:
    """Validate automation specs against the ontology and the configured agents."""
    out: Dict[str, Automation] = {}
    for name, spec in (specs or {}).items():
        where = f"automation {name!r}"
        entity = spec.get("entity")
        if entity not in ontology.entities:
            raise OntologyError(f"{where}: unknown entity {entity!r}")
        when = None
        if spec.get("when"):
            try:
                when = ontology.expression(spec["when"])
            except ExpressionError as exc:
                raise OntologyError(f"{where}: {exc}") from None
            ontology._check_expr(when, where, allow_params=True, only=entity)
            bad = [a for e, a in when.references if e == PARAMS and a != "now"]
            if bad:
                raise OntologyError(f"{where}: the only parameter is Params.now, not {bad}")
            if when.quantifiers:
                raise OntologyError(f"{where}: conditions apply to one instance; quantifiers are not allowed")
        trigger = spec.get("trigger", "change")
        every = None
        if isinstance(trigger, Mapping):
            every = trigger.get("every")
            if not isinstance(every, (int, float)) or every <= 0:
                raise OntologyError(f"{where}: trigger every must be a positive number of seconds")
        elif trigger != "change":
            raise OntologyError(f"{where}: trigger must be \"change\" or {{\"every\": seconds}}")
        run, notify = spec.get("run"), spec.get("notify")
        if not run and not notify:
            raise OntologyError(f"{where}: needs a run, a notify, or both")
        if run:
            agent, goal, template = run.get("agent"), run.get("goal"), run.get("case_template")
            if agent not in agent_goals:
                raise OntologyError(f"{where}: unknown agent {agent!r}")
            if goal not in agent_goals[agent]:
                raise OntologyError(f"{where}: agent {agent} may not pursue goal {goal!r}")
            tpl = ontology.case_templates.get(template)
            if tpl is None:
                raise OntologyError(f"{where}: unknown case template {template!r}")
            if tpl.root != entity:
                raise OntologyError(f"{where}: case template {template} starts at {tpl.root}, not {entity}")
            run = {"write_back": True, **run}
        if notify:
            if not notify.get("roles"):
                raise OntologyError(f"{where}: notify needs roles")
            etype = ontology.entities[entity]
            for ph in PLACEHOLDER.findall(str(notify.get("message", ""))):
                if ph != ID and not etype.has_attribute(ph):
                    raise OntologyError(f"{where}: message placeholder {{{ph}}} is not an attribute of {entity}")
        retry = dict(spec.get("retry") or {})
        retry_after, max_retries = retry.get("after", 300), retry.get("max", 5)
        if not isinstance(retry_after, (int, float)) or retry_after < 0 or not isinstance(max_retries, int) \
                or isinstance(max_retries, bool) or max_retries < 1:
            raise OntologyError(f"{where}: retry needs after >= 0 seconds and max >= 1 attempts")
        out[name] = Automation(name, entity, when, float(every) if every else None, run, notify,
                               spec.get("description", ""), float(retry_after), max_retries)
    return out


@dataclass
class Firing:
    automation: str
    instance: str
    trigger: str  # change | schedule | manual
    run_id: Optional[str] = None
    status: str = "fired"  # fired | completed | awaiting_review | ... (run status) | notified | error
    detail: str = ""
    notification_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Automator:
    """Evaluates automations against the graph and fires them; persistence goes through ``store``.

    ``fire(automation, instance, trigger)`` performs the work (start the run, record notifications)
    and returns a :class:`Firing`. It is supplied by the service, so this class stays independent of
    agents and HTTP.
    """

    automations: Mapping[str, Automation]
    store: Any
    instances: Callable[[Optional[str]], List[Instance]]  # entity type -> instances (None = all)
    fire: Callable[[Automation, Instance, str], Firing]
    clock: Callable[[], float] = time.time
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _queue: List[str] = field(default_factory=list)
    _busy: bool = False

    def on_change(self, instance_ids: Iterable[str]) -> List[Firing]:
        """Evaluate ``change`` automations for instances that were just written."""
        with self._lock:
            self._queue.extend(instance_ids)
            if self._busy:  # a firing wrote back: picked up by the outer pass
                return []
            self._busy = True
            fired: List[Firing] = []
            try:
                while self._queue and len(fired) < MAX_FIRINGS_PER_PASS:
                    ids = list(dict.fromkeys(self._queue))
                    self._queue.clear()
                    by_id = {i.id: i for i in self.instances(None) if i.id in set(ids)}
                    for iid in ids:
                        if iid in by_id:
                            fired += self._evaluate_change(by_id[iid], self.clock())
            finally:
                self._queue.clear()
                self._busy = False
            return fired

    def tick(self) -> List[Firing]:
        """Re-evaluate every automation over all its instances (scheduled triggers and time-based conditions)."""
        with self._lock:
            now = self.clock()
            ids: List[str] = []
            fired: List[Firing] = []
            self._busy = True
            try:
                for auto in self.automations.values():
                    for inst in self.instances(auto.entity):
                        if auto.every is None:
                            fired += self._evaluate_change(inst, now, only=auto.name)
                        elif auto.holds(inst, now):
                            last = self.store.automation_state(auto.name, inst.id)
                            if last is None or last["last_fired"] is None or now - last["last_fired"] >= auto.every:
                                fired.append(self._fire(auto, inst, "schedule", now))
                ids = list(self._queue)
            finally:
                self._queue.clear()
                self._busy = False
            return fired + (self.on_change(ids) if ids else [])

    def run_now(self, name: str, instance: Optional[str] = None) -> List[Firing]:
        """Fire an automation by hand: for one instance, or for every instance where it holds."""
        auto = self.automations[name]
        now = self.clock()
        targets = [i for i in self.instances(auto.entity) if (i.id == instance if instance else auto.holds(i, now))]
        if instance and not targets:
            raise KeyError(instance)
        with self._lock:
            return [self._fire(auto, inst, "manual", now) for inst in targets]

    # -- internals ----------------------------------------------------------
    def _evaluate_change(self, inst: Instance, now: float, only: Optional[str] = None) -> List[Firing]:
        fired = []
        for auto in self.automations.values():
            if auto.every is not None or auto.entity != inst.type or (only and auto.name != only):
                continue
            holds = auto.holds(inst, now)
            state = self.store.automation_state(auto.name, inst.id)
            active = bool(state and state["active"])
            failures = int(state.get("failures") or 0) if state else 0
            if holds and not active:
                if failures and state["last_fired"] is not None and now - state["last_fired"] < auto.retry_seconds:
                    continue  # the last attempt errored: wait before retrying
                fired.append(self._fire(auto, inst, "change" if not failures else "retry", now))
            elif not holds and active:
                self.store.set_automation_state(auto.name, inst.id, False)
        return fired

    def _fire(self, auto: Automation, inst: Instance, trigger: str, now: float) -> Firing:
        """Fire once. A firing that raises is not done: it stays armed and is retried after
        ``retry_seconds``, up to ``max_retries`` attempts; then the automation gives up on that instance."""
        import logging

        log = logging.getLogger("autology.automation")
        state = self.store.automation_state(auto.name, inst.id)
        failures = int(state.get("failures") or 0) if state else 0
        self.store.set_automation_state(auto.name, inst.id, True, now)  # before firing: no double fire on re-entry
        try:
            firing = self.fire(auto, inst, trigger)
            if failures:
                self.store.set_automation_failures(auto.name, inst.id, 0)
        except Exception as exc:  # an automation failing must not stop the others
            log.exception("automation %s on %s failed", auto.name, inst.id)
            failures += 1
            detail = f"{type(exc).__name__}: {exc}"
            if failures >= auto.max_retries:  # stays active: no more attempts until the condition re-arms
                log.warning("automation %s: giving up on %s after %d failed attempts", auto.name, inst.id, failures)
                firing = Firing(auto.name, inst.id, trigger, status="gave_up",
                                detail=f"{detail}; giving up after {failures} attempts")
            else:
                self.store.set_automation_state(auto.name, inst.id, False, now)  # re-arm for a retry
                firing = Firing(auto.name, inst.id, trigger, status="error",
                                detail=f"{detail}; retry {failures + 1} of {auto.max_retries} after "
                                       f"{auto.retry_seconds:g}s")
            self.store.set_automation_failures(auto.name, inst.id, failures)
        self.store.record_firing(firing)
        return firing
