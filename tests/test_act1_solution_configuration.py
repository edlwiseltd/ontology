"""Activation sprint, increment A: agents and simulated tools configured through the versioned API (for Studio).

  S1 the catalogue is small and approved: three simulated tools; connectors, custom code and model reasoners are
     listed as unavailable with the reason, and cannot be assigned
  S2 the engine validates a configuration against the draft's model and names every problem; a valid one compiles
     to decision tables only (environment ``simulated``): no configuration step can enable an external action
  S3 a configuration is saved as a draft revision together with the model: saving one part carries the other
     over; a stale save is refused; an invalid configuration is never stored; it can be withdrawn; history is kept
  S4 saving changes nothing that runs: the engine's agents, tools and configuration fingerprint are what they were
  S5 effective permissions say, per action, what an agent may do, and never more than the model's rules allow:
     a missing role refuses, a review rule stays a review, a decision-critical fact needs its writer rule
  S6 autonomy can only be narrowed: ``supervised`` adds reviews by a named role at run time and removes none;
     that reviewer role is one a pilot requires a member to hold
  S7 ``configure`` saves, ``read`` reads, others are refused; a use case whose agents an operator configured in
     files is not editable from Studio
  S8 a starting configuration is suggested by the engine and is itself validated
  S9 another workspace cannot read or change a configuration; answers follow the published contract
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from autology import Ontology, WorkAgent, solution
from autology.agent import DeferredApprover, ReviewDecision
from autology.openapi import SCHEMAS
from autology.server import ApiError, ApiExchange
from autology.simulation import sample_case
from autology.tools import ToolRegistry, ToolResult

from . import test_ingest
from .schema_check import errors
from .test_onb1_draft_simulation import proposed_model
from .test_workspaces import Client, platform


def engine(**overrides):
    """An engine with an empty model, no agent, the sandbox architect and two members."""
    path = Path(tempfile.mkdtemp()) / "ontology.json"
    path.write_text(json.dumps({"name": "new-solution", "version": "0.1.0"}))
    os.environ.update({"AUTOLOGY_TOKEN_CLARA": "tok-clara", "AUTOLOGY_TOKEN_RAY": "tok-ray", "AUTOLOGY_TOKEN_OPS": "tok-ops"})
    users = [{"name": "clara", "token_env": "AUTOLOGY_TOKEN_CLARA", "permissions": ["configure", "read"]},
             {"name": "ray", "token_env": "AUTOLOGY_TOKEN_RAY", "permissions": ["read"]},
             {"name": "ops", "token_env": "AUTOLOGY_TOKEN_OPS", "permissions": ["run"]}]
    config = {"ontology": str(path), "agents": {}, "data": None, "pipelines": {}, "users": users,
              "service_identities": {}, "automations": {}, "ai": {"provider": "sandbox"}, **overrides}
    return test_ingest.service(**config)


BROKEN = {"name": "x", "version": "1.0.0", "rules": [{"id": "R", "type": "magic"}]}  # a model the loader refuses


def good(**agent):
    """A valid configuration for the service-request model."""
    base = {"purpose": "Takes a request to closure", "responsibilities": ["review", "fulfil"],
            "roles": ["service_agent"], "goals": ["request_closed"], "autonomy": {"mode": "policy"},
            "tools": [{"action": "review_request", "tool": "simulated.succeed"},
                      {"action": "approve_request", "tool": "simulated.succeed", "message": "approved (simulated)"},
                      {"action": "fulfil_request", "tool": "simulated.decision_table", "rows": [
                          {"when": "Request.priority == 'urgent'", "message": "courier (simulated)"},
                          {"message": "standard delivery (simulated)"}]},
                      {"action": "notify_requester", "tool": "simulated.fail", "error": "mail server down",
                       "when": "Request.title == 'FAIL'"},
                      {"action": "close_request", "tool": "simulated.succeed"}]}
    return {"agents": {"request_handler": {**base, **agent}}}


class Base(unittest.TestCase):
    def setUp(self):
        self.svc = engine()
        self.addCleanup(self.svc.close)
        self.u = {x.name: x for x in self.svc.users}
        self.doc = proposed_model()
        self.svc.save_model_draft(self.u["clara"], {"document": self.doc, "expected_revision": 0, "note": "model"})
        self.api = self.svc.configuring

    def save(self, candidate, revision=None, user="clara"):
        revision = self.svc.store.draft()["revision"] if revision is None else revision
        return self.api.save_solution_draft(self.u[user], {"solution": candidate, "expected_revision": revision})


class CatalogueAndValidationTests(Base):
    def test_the_catalogue_is_small_approved_and_simulated(self):  # S1
        items = {i["id"]: i for i in self.api.tool_catalog(self.u["ray"])["items"]}
        self.assertEqual(sorted(k for k, v in items.items() if v["available"]),
                         ["simulated.decision_table", "simulated.fail", "simulated.succeed"])
        self.assertTrue(all(v["environment"] == "simulated" for v in items.values() if v["available"]))
        self.assertEqual(sorted(k for k, v in items.items() if not v["available"]),
                         ["connector.code", "connector.http", "model.reasoner"])
        self.assertIn("D7", items["model.reasoner"]["description"])
        for tool in ("connector.http", "connector.code", "model.reasoner", "shell.exec"):
            out = self.api.validate_solution(self.u["clara"], {"solution": good(tools=[
                {"action": "fulfil_request", "tool": tool, "url": "https://erp.example.com"}])})
            self.assertEqual((out["state"], out["simulated_tools"]), ("invalid", []), tool)
            with self.assertRaises(ApiError):
                self.save(good(tools=[{"action": "fulfil_request", "tool": tool}]))

    def test_every_problem_is_named_and_a_valid_configuration_is_only_decision_tables(self):  # S2
        bad = {"agents": {
            "bad name": {},
            "x": {"goals": ["world_peace"], "roles": ["r"], "color": "red", "autonomy": {"mode": "free"},
                  "tools": [{"action": "launch_rocket", "tool": "simulated.succeed"},
                            {"action": "close_request", "tool": "simulated.decision_table", "rows": [
                                {"when": "Request.zzz > 1", "outcome": "maybe", "updates": {"Request": {"amount": 1}}}]},
                            {"action": "review_request", "tool": "simulated.succeed", "url": "http://x"},
                            {"action": "review_request", "tool": "simulated.succeed"},
                            {"action": "fulfil_request", "tool": "simulated.fail", "when": "not an expression ("}]}},
            "sample_data": {"instances": [{"type": "Ghost", "id": "g-1"}]}}
        out = self.api.validate_solution(self.u["clara"], {"solution": bad})
        self.assertEqual((out["state"], out["validation"]["valid"]), ("invalid", False))
        found = {p["path"]: p["message"] for p in out["validation"]["problems"]}
        for path, text in (("agents.bad name", "simple name"), ("agents.x", "unknown keys ['color']"),
                           ("agents.x.goals", "no goal 'world_peace'"), ("agents.x.tools[0]", "no action 'launch_rocket'"),
                           ("agents.x.tools[1].rows[0].when", "no Request.zzz"),
                           ("agents.x.tools[1].rows[0].outcome", "not 'maybe'"),
                           ("agents.x.tools[1].rows[0].updates", "may write no field"),
                           ("agents.x.tools[2]", "no parameter ['url']"), ("agents.x.tools[3]", "already has a tool"),
                           ("agents.x.tools[4].when", "not a valid condition"), ("agents.x.autonomy", "supervised"),
                           ("sample_data", "do not fit the model")):
            self.assertIn(text, found.get(path, ""), path)
        ok = self.api.validate_solution(self.u["clara"], {"solution": good()})
        self.assertEqual((ok["state"], ok["validation"]["problems"]), ("validated", []))
        self.assertEqual(ok["simulated_tools"], sorted(f"request_handler.{a}" for a in (
            "review_request", "approve_request", "fulfil_request", "notify_requester", "close_request")))
        compiled = solution.compile_solution(good(), self.doc)["agents"]["request_handler"]
        self.assertEqual({t["type"] for t in compiled["tools"]["tools"]}, {"table"})  # nothing else can come out
        self.assertEqual((compiled["approver"], compiled["managed"]), ("inbox", "studio"))
        self.assertEqual(compiled["tools"]["tools"][3]["rows"][0], {"when": "Request.title == 'FAIL'",
                                                                    "error": "mail server down"})
        for not_a_solution in ("agents", {"agents": [], "extra": 1}, {"agents": {str(i): {} for i in range(13)}}):
            self.assertFalse(self.api.validate_solution(self.u["clara"], {"solution": not_a_solution})["validation"]["valid"])
        with self.assertRaises(solution.SolutionError):
            solution.compile_solution(bad, self.doc)
        self.assertIsNone(solution.check(good(), BROKEN)[1])  # no valid model, no compilation
        self.assertIsNone(solution.check(good(), None)[1])

    def test_a_starting_configuration_is_suggested_and_validated(self):  # S8
        out = self.api.suggest_solution(self.u["clara"], {})
        self.assertEqual((out["source"], out["saved"], out["state"]), ("generic", False, "validated"))
        agent = out["solution"]["agents"]["solution_agent"]
        self.assertEqual((agent["roles"], agent["goals"], len(agent["tools"])),
                         (["manager", "service_agent"], ["request_closed"], 6))
        self.assertTrue(all(t["tool"] == "simulated.succeed" for t in agent["tools"]))
        self.assertEqual(self.svc.store.draft()["solution"], None)  # a suggestion is not a save
        with self.assertRaises(ApiError):
            self.api.suggest_solution(self.u["clara"], {"proposal": "P-nothing"})
        with self.assertRaises(ApiError):
            self.api.suggest_solution(self.u["clara"], {"document": BROKEN})
        self.assertEqual(solution.suggest({"name": "empty", "version": "1.0.0"})["agents"], {})


class DraftTests(Base):
    def test_model_and_configuration_are_one_draft(self):  # S3, S4
        before = (sorted(self.svc.agents), self.svc.configuration_fingerprint, self.svc.ontology.fingerprint)
        out = self.save(good())
        self.assertEqual((out["revision"], out["state"], out["author"]), (2, "validated", "clara"))
        row = self.svc.store.draft()
        self.assertEqual((row["document"], row["solution"]), (self.doc, good()))  # the model was carried over
        # saving the model alone keeps the configuration
        edited = {**self.doc, "description": "edited"}
        self.svc.save_model_draft(self.u["clara"], {"document": edited, "expected_revision": 2, "note": "model only"})
        row = self.svc.store.draft()
        self.assertEqual((row["revision"], row["document"]["description"], row["solution"]), (3, "edited", good()))
        with self.assertRaises(ApiError) as stale:
            self.save(good(purpose="late"), revision=2)
        self.assertEqual((stale.exception.status, stale.exception.extra["revision"]), (409, 3))
        with self.assertRaises(ApiError) as invalid:
            self.save(good(goals=["nope"]))
        self.assertEqual(invalid.exception.status, 400)
        self.assertEqual(invalid.exception.extra["problems"][0]["path"], "agents.request_handler.goals")
        self.assertEqual(self.svc.store.draft()["revision"], 3)  # nothing invalid was stored
        # a configuration that no longer fits an edited model is reported, not silently kept as valid
        smaller = {**self.doc, "actions": {k: v for k, v in self.doc["actions"].items() if k != "notify_requester"},
                   "rules": [r for r in self.doc["rules"] if r["id"] != "R-NOTIFY"]}
        self.svc.save_model_draft(self.u["clara"], {"document": smaller, "expected_revision": 3})
        view = self.api.solution_draft(self.u["clara"])
        self.assertEqual(view["state"], "invalid")
        self.assertIn("no action 'notify_requester'", view["validation"]["problems"][0]["message"])
        # withdrawn: the next revision has no configuration; earlier revisions are still there
        withdrawn = self.save(None)
        self.assertEqual((withdrawn["revision"], withdrawn["solution"], withdrawn["state"]), (5, None, "none"))
        self.assertEqual(self.svc.store.draft(2)["solution"], good())
        self.assertEqual([h["revision"] for h in self.svc.store.draft_history()], [1, 2, 3, 4, 5])
        for body in ({"solution": "agents", "expected_revision": 5}, {"solution": good()},
                     {"solution": good(), "expected_revision": True}):
            with self.assertRaises(ApiError):
                self.api.save_solution_draft(self.u["clara"], body)
        # none of this changed what runs
        self.assertEqual((sorted(self.svc.agents), self.svc.configuration_fingerprint, self.svc.ontology.fingerprint),
                         before)

    def test_the_view_says_what_is_draft_and_what_runs(self):  # S3, S4
        empty = self.api.solution_draft(self.u["ray"])
        self.assertEqual((empty["state"], empty["solution"], empty["active"]["managed"], empty["active"]["editable"]),
                         ("none", None, "none", True))
        self.assertEqual(errors(empty, SCHEMAS["SolutionDraft"], SCHEMAS), [])
        saved = self.save(good())
        self.assertEqual(errors(saved, SCHEMAS["SolutionDraft"], SCHEMAS), [])
        self.assertEqual(saved["changes"], [{"kind": "agent", "name": "request_handler", "change": "added", "fields": []}])
        self.assertEqual((saved["active"]["agents"], saved["active"]["solution"]), ([], None))  # still nothing runs
        self.assertEqual(solution.changes(good(), good(roles=["x"], purpose="p")),
                         [{"kind": "agent", "name": "request_handler", "change": "changed", "fields": ["purpose", "roles"]}])
        self.assertEqual([c["change"] for c in solution.changes({**good(), "sample_data": {"instances": []}}, {"agents": {}})],
                         ["removed", "removed"])

    def test_who_may_read_and_save(self):  # S7
        self.assertEqual(self.api.solution_draft(self.u["ray"])["revision"], 1)
        for user in ("ray", "ops"):
            with self.assertRaises(ApiError) as refused:
                self.save(good(), user=user)
            self.assertEqual(refused.exception.status, 403, user)
        for call in (self.api.solution_draft, self.api.tool_catalog):
            with self.assertRaises(ApiError):
                call(self.u["ops"])
        with self.assertRaises(ApiError):
            self.api.suggest_solution(self.u["ray"], {})
        ex = ApiExchange(self.svc, "POST", "/api/v1/solution/draft", {"Authorization": "Bearer tok-clara"},
                         json.dumps({"solution": good(), "expected_revision": 1}).encode()).run()
        self.assertEqual((ex.status, json.loads(ex.data)["revision"]), (200, 2))
        self.assertEqual(ApiExchange(self.svc, "GET", "/api/v1/tools/catalog", {"Authorization": "Bearer tok-ops"},
                                     b"").run().status, 403)
        # agents an operator configured in files are shown, never replaced from Studio
        files = test_ingest.service(automations={})
        self.addCleanup(files.close)
        admin = next(u for u in files.users if u.name == "admin")
        view = files.configuring.solution_draft(admin)
        self.assertEqual((view["active"]["managed"], view["active"]["editable"], view["active"]["agents"]),
                         ("files", False, ["claims"]))
        with self.assertRaises(ApiError) as refused:
            files.configuring.save_solution_draft(admin, {"solution": {"agents": {}}, "expected_revision": 0})
        self.assertEqual(refused.exception.status, 409)


class PermissionTests(Base):
    def rows(self, candidate, doc=None):
        return {r["action"]: r for r in solution.effective_permissions(candidate, doc or self.doc)["request_handler"]}

    def test_an_agent_never_gets_more_than_the_rules_allow(self):  # S5
        rows = self.rows(good())
        self.assertEqual({a: r["status"] for a, r in rows.items()}, {
            "review_request": "autonomous", "approve_request": "conditional", "reject_request": "not_assigned",
            "fulfil_request": "autonomous", "notify_requester": "autonomous", "close_request": "autonomous"})
        self.assertEqual(rows["approve_request"]["reviews"],
                         [{"reviewer": "manager", "when": "Request.amount >= 1000", "rule": "R-APPROVAL"}])
        self.assertTrue(all(r["simulated"] for r in rows.values() if r["tool"]))
        # without the role the action rule names, the agent is refused whatever tool it was given
        rows = self.rows(good(roles=["intern"]))
        self.assertEqual(rows["fulfil_request"]["status"], "refused")
        self.assertIn("R-FULFIL: only service_agent may perform it", rows["fulfil_request"]["refused"])
        # an unconditional review rule stays a review, whatever the autonomy says
        with_reject = good()
        with_reject["agents"]["request_handler"]["tools"].append({"action": "reject_request", "tool": "simulated.succeed"})
        self.assertEqual(self.rows(with_reject)["reject_request"]["status"], "review_required")
        # a decision-critical fact the agent would write needs a writer rule naming one of its roles
        critical = json.loads(json.dumps(self.doc))
        critical["entities"]["Request"]["attributes"]["amount"] = {"type": "number", "decision_critical": True}
        critical["actions"]["approve_request"]["writes"] = ["Request.amount"]
        rows = self.rows(good(), critical)
        self.assertEqual(rows["approve_request"]["status"], "refused")
        self.assertIn("decision-critical", " ".join(rows["approve_request"]["refused"]))
        self.assertEqual(self.rows(good(roles=["service_agent", "manager"]), critical)["approve_request"]["status"],
                         "conditional")
        self.assertEqual(solution.effective_permissions(good(), BROKEN), {})
        self.assertEqual(solution.effective_permissions("agents", self.doc), {})
        view = self.api.validate_solution(self.u["clara"], {"solution": good()})
        self.assertEqual(errors(view, SCHEMAS["SolutionDraft"], SCHEMAS), [])
        self.assertEqual(view["permissions"]["request_handler"][0]["action"], "review_request")

    def test_autonomy_is_only_ever_narrowed(self):  # S6
        supervised = good(autonomy={"mode": "supervised", "reviewer": "duty_lead"})
        rows = self.rows(supervised)
        self.assertEqual((rows["fulfil_request"]["status"], rows["review_request"]["status"]),
                         ("review_required", "autonomous"))  # what acts outside waits; an internal step does not
        self.assertEqual(rows["fulfil_request"]["reviews"], [{"reviewer": "duty_lead", "when": None, "rule": "agent autonomy"}])
        chosen = good(autonomy={"mode": "supervised", "reviewer": "duty_lead", "actions": ["close_request"]})
        self.assertEqual({a for a, r in self.rows(chosen).items() if r["status"] == "review_required"}, {"close_request"})
        for bad in ({"mode": "supervised"}, {"mode": "policy", "reviewer": "x"}, {"mode": "none"},
                    {"mode": "supervised", "reviewer": "x", "actions": ["reject_request"]}, "policy"):
            self.assertFalse(self.api.validate_solution(self.u["clara"], {"solution": good(autonomy=bad)})["validation"]["valid"], bad)
        # at run time, on the engine's own agent
        onto = Ontology.from_dict(self.doc)
        case = sample_case(onto, self.doc)
        case["Request"]["amount"] = 5  # below the rule's threshold: the model asks for no review

        def run(**kw):
            tools, approver = ToolRegistry(), DeferredApprover()
            for capability in sorted({a.capability for a in onto.actions.values()}):
                tools.register(capability, capability, lambda call: ToolResult(), environment="simulated")
            agent = WorkAgent("request_handler", onto, tools, roles=["service_agent"], approver=approver, **kw)
            return agent, approver, agent.run("request_closed", case)

        _, approver, result = run()
        self.assertEqual((result.status, approver.requests), ("completed", []))  # policy: nobody is asked
        agent, approver, result = run(autonomy={"mode": "supervised", "reviewer": "duty_lead"})
        self.assertEqual((result.status, approver.requests[-1].action, approver.requests[-1].reviewers,
                          approver.requests[-1].rule_ids), ("awaiting_review", "fulfil_request", ("duty_lead",), ["AUTONOMY"]))
        result = agent.resume(result, decision=ReviewDecision(False, "lea"))
        self.assertNotEqual(result.status, "completed")  # a refusal by the supervisor is a refusal
        self.assertNotIn("fulfil_request:done", result.path)
        # a review the rules ask for is still asked for, by the rule's role
        case["Request"]["amount"] = 5000
        _, approver, result = run(autonomy={"mode": "supervised", "reviewer": "duty_lead", "actions": ["close_request"]})
        self.assertEqual((approver.requests[-1].action, approver.requests[-1].reviewers), ("approve_request", ("manager",)))
        for bad in ({"mode": "free"}, {"mode": "supervised"}):
            with self.assertRaises(ValueError):
                run(autonomy=bad)

    def test_the_engine_runs_a_compiled_configuration_with_simulated_tools_only(self):  # S2, S6
        compiled = solution.compile_solution(good(autonomy={"mode": "supervised", "reviewer": "duty_lead"}), self.doc)
        path = Path(tempfile.mkdtemp()) / "model.json"
        path.write_text(json.dumps(self.doc))
        svc = engine(ontology=str(path), agents=compiled["agents"])
        self.addCleanup(svc.close)
        agent = svc.agents["request_handler"].agent
        self.assertEqual({t.environment for t in agent.tools}, {"simulated"})
        self.assertEqual((len(list(agent.tools)), agent.autonomy["reviewer"], sorted(agent.principal.roles)),
                         (5, "duty_lead", ["service_agent"]))
        from autology.lifecycle import evaluate
        reviewers = next(c for c in evaluate("pilot", svc) if c.id == "reviewers_assigned")
        self.assertIn("duty_lead", reviewers.detail)  # the supervisor role must be held before a pilot
        self.assertFalse(reviewers.passed)


class IsolationTests(unittest.TestCase):
    def test_another_workspace_cannot_read_or_change_a_configuration(self):  # S9
        pf = platform()
        c = Client(pf)
        try:
            base = "/w/acme/u/claims/api/v1/solution"
            status, view = c.call("GET", f"{base}/draft", "acme-ada")
            self.assertEqual((status, view["active"]["managed"]), (200, "files"))
            self.assertEqual(errors(view, SCHEMAS["SolutionDraft"], SCHEMAS), [])
            self.assertEqual(c.call("GET", f"{base}/draft", "nw-nadia")[0], 404)
            self.assertEqual(c.call("POST", f"{base}/draft", "nw-nadia", {"solution": None, "expected_revision": 0})[0], 404)
            self.assertEqual(c.call("POST", f"{base}/draft", "acme-ada", {"solution": {"agents": {}}, "expected_revision": 0})[0], 409)
            self.assertEqual(c.call("POST", f"{base}/draft", "acme-hana", {"solution": None, "expected_revision": 0})[0], 403)
            status, catalogue = c.call("GET", "/w/acme/u/claims/api/v1/tools/catalog", "acme-ada")
            self.assertEqual((status, errors(catalogue, SCHEMAS["ToolCatalog"], SCHEMAS)), (200, []))
            self.assertEqual(c.call("GET", "/w/acme/u/claims/api/v1/tools/catalog", None)[0], 401)
        finally:
            c.server.shutdown()
            c.server.server_close()
            pf.close()


if __name__ == "__main__":
    unittest.main()
