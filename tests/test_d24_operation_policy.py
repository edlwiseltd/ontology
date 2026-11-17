"""D24, least-privilege operations: the proposed semantics, tested without being in force (synthetic fixtures).

  P1 nothing that runs uses the proposal; the Engine's permissions are the eight they were
  P2 twelve operations, each with what lets it through today, what would, and where the Engine would enforce it
  P3 a grant counts only when a person other than its proposer and its holder approved it
  P4 the positive cases: each of the ten operations a caller can do, with exactly the right it needs
  P5 the negative cases: another workspace, another use case, another entity type, another property, a state, a
     decision-critical property, a write rule, a hidden record, a workflow state, open work, a service identity,
     one's own request, one's own grant, and the two operations no caller does
  P6 no right implies another; the unrestricted permission passes where it passes today and is bound by the rules
  P7 a form, a manifest or a screen is not an input: the function does not read one
"""

import inspect
import unittest
from pathlib import Path

from autology import operation_policy, platform, runs, server
from autology.operation_policy import NEW_RIGHTS, OPERATIONS, decide, in_force

ROOT = Path(__file__).resolve().parent.parent
MODEL = {"entities": {
    "Ticket": {"properties": ["title", "size", "verdict", "note"], "decision_critical": ["size", "verdict"],
               "write_access": {"size": ["estimator"], "note": ["auditor"]}, "archivable": True},
    "Owner": {"properties": ["label"], "decision_critical": [], "write_access": {}}}}


def grant(permission, member="pat", **more):
    return {"member": member, "workspace": "w1", "use_case": "u1", "permission": permission, "proposed_by": "ada",
            "approved_by": "bo", **more}


def ask(operation, **more):
    identity = {"name": "pat", "kind": "person", "roles": ["worker"], **more.pop("identity", {})}
    return {"workspace": "w1", "use_case": "u1", "operation": operation, "identity": identity, "entity": "Ticket",
            "record": {"visible": True, "state": "open"}, **more}


CREATE = grant("records.create", entities=["Ticket"], properties={"Ticket": ["title"]})
UPDATE = grant("records.update", entities=["Ticket"], properties={"Ticket": ["title", "size", "note"]}, states=["open"])
ARCHIVE = grant("records.archive", entities=["Ticket"])
ADMIN = grant("admin", unrestricted=True)


class NotInForceTests(unittest.TestCase):
    def test_nothing_that_runs_uses_the_proposal(self):  # P1
        package = ROOT / "autology"
        users = [p.name for p in package.glob("*.py")
                 if p.name != "operation_policy.py" and "operation_policy" in p.read_text(encoding="utf-8")]
        self.assertEqual(users, [])
        self.assertIn("not in force", operation_policy.POLICY)
        self.assertIn("**not in force**", operation_policy.__doc__)
        self.assertEqual(server.PERMISSIONS, frozenset({"read", "run", "review", "audit", "ingest", "reconcile", "configure", "admin"}))
        self.assertFalse(set(NEW_RIGHTS) & server.PERMISSIONS)
        self.assertNotIn("operate", server.PERMISSIONS)
        self.assertFalse(decide(ask("records.read"), [grant("read")], MODEL)["in_force"])

    def test_twelve_operations_and_where_each_would_be_enforced(self):  # P2
        self.assertEqual(list(OPERATIONS), [
            "records.read", "records.create", "records.update", "records.archive", "actions.request", "actions.execute",
            "reviews.request", "reviews.decide", "data.administer", "ontology.modify", "releases.manage", "permissions.administer"])
        self.assertEqual(NEW_RIGHTS, ["records.archive", "records.create", "records.update"])
        self.assertEqual([k for k, o in OPERATIONS.items() if not o["caller"]], ["actions.execute", "reviews.request"])
        modules = {"server": server, "platform": platform, "runs": runs}
        for name, spec in OPERATIONS.items():
            for place in spec["enforced"].split(", "):  # a named enforcement point exists in the code
                target = modules[place.split(".")[0]]
                for part in place.split(".")[1:]:
                    target = getattr(target, part)
                self.assertTrue(inspect.isclass(target) or callable(target), (name, place))
        self.assertNotIn("admin", [o["right"] for k, o in OPERATIONS.items() if k != "data.administer"])  # never routine


class GrantTests(unittest.TestCase):
    def test_a_grant_counts_once_a_second_person_approved_it(self):  # P3
        self.assertTrue(in_force(grant("read")))
        for broken in ({"approved_by": None}, {"approved_by": "ada"}, {"approved_by": "pat"}, {"approver_kind": "service"}):
            g = grant("records.create", entities=["Ticket"], properties={"Ticket": ["title"]}, **broken)
            self.assertFalse(in_force(g), broken)
            out = decide(ask("records.create", properties=["title"]), [g], MODEL)
            self.assertEqual((out["allowed"], out["status"], out["check"]), (False, 403, "grant"), broken)


class PositiveTests(unittest.TestCase):
    def ok(self, request, grants, check="grant"):
        out = decide(request, grants, MODEL)
        self.assertEqual((out["allowed"], out["status"], out["check"]), (True, 200, check), out)
        return out

    def test_each_operation_with_exactly_the_right_it_needs(self):  # P4
        self.ok(ask("records.read"), [grant("read")])
        self.ok(ask("records.create", properties=["title"]), [CREATE])
        self.ok(ask("records.update", properties=["title"]), [UPDATE])
        self.ok(ask("records.update", properties=["size"], identity={"roles": ["estimator"]}), [UPDATE])
        self.ok(ask("records.archive"), [ARCHIVE])
        self.ok(ask("actions.request"), [grant("run")])
        self.ok(ask("reviews.decide", identity={"reviewer_roles": ["lead"]}, review={"reviewer_roles": ["lead"], "requested_by": "sam"}),
                [grant("review")])
        self.ok(ask("data.administer"), [ADMIN])
        self.ok(ask("ontology.modify"), [grant("configure")])
        for operation in ("releases.manage", "permissions.administer"):
            self.ok(ask(operation, identity={"office": ["administrator"]}, target="sam"), [], check="office")
        # a service identity may hold the record rights (an intake integration)
        robot = {"name": "intake", "kind": "service", "roles": []}
        self.ok(ask("records.create", identity=robot, properties=["title"]), [{**CREATE, "member": "intake"}])

    def test_the_unrestricted_permission_passes_where_it_does_today_and_no_further(self):  # P6
        self.ok(ask("records.create", properties=["title", "note"], identity={"roles": ["auditor"]}), [ADMIN], check="unrestricted")
        self.ok(ask("records.update", properties=["title"]), [ADMIN], check="unrestricted")
        for request, check in ((ask("records.update", properties=["verdict"]), "rule"),      # decision-critical: binds every writer
                               (ask("records.update", properties=["status"]), "state"),
                               (ask("records.update", properties=["note"]), "rule"),         # a write rule names another role
                               (ask("records.archive"), "grant"),                            # no deletion or archive by office
                               (ask("actions.request"), "grant"), (ask("records.read"), "grant"),
                               (ask("reviews.decide", review={"reviewer_roles": ["lead"]}), "grant")):
            out = decide(request, [ADMIN], MODEL)
            self.assertEqual((out["allowed"], out["check"]), (False, check), out)


class NegativeTests(unittest.TestCase):
    def no(self, request, grants, status, check):
        out = decide(request, grants, MODEL)
        self.assertEqual((out["allowed"], out["status"], out["check"]), (False, status, check), out)
        self.assertEqual(out["policy"], operation_policy.POLICY)
        return out

    def test_scope(self):  # P5
        everything = [grant("read"), grant("run"), CREATE, UPDATE, ARCHIVE]
        self.no(ask("records.read", workspace="w2"), everything, 403, "grant")
        self.no(ask("records.update", use_case="u2", properties=["title"]), everything, 403, "grant")
        self.no(ask("records.read", identity={"name": "sam"}), everything, 403, "grant")
        self.no(ask("records.read", identity={"kind": "anonymous"}), everything, 401, "identity")
        self.no(ask("records.export"), everything, 400, "operation")
        self.no(ask("records.create", entity="Owner", properties=["label"]), everything, 403, "entity")
        self.no(ask("records.create", entity="Invented"), everything, 400, "entity")
        self.no(ask("records.create", properties=["note"]), everything, 403, "rule")         # the write rule comes first
        self.no(ask("records.create", properties=["title", "size"], identity={"roles": ["estimator"]}), everything, 403, "properties")
        self.no(ask("records.update", properties=["missing"]), everything, 400, "properties")

    def test_rules_stand_above_grants(self):  # P5
        generous = grant("records.update", entities=["Ticket"], properties={"Ticket": ["title", "size", "verdict", "note", "status"]})
        self.no(ask("records.update", properties=["status"]), [generous], 403, "state")
        self.no(ask("records.create", properties=["title"], sets_state=True), [CREATE], 403, "state")
        self.no(ask("records.update", properties=["verdict"]), [generous], 403, "rule")      # decision-critical, no writer rule
        self.no(ask("records.update", properties=["size"]), [generous], 403, "rule")         # writer rule names another role
        self.no(ask("records.update", properties=["title"], record={"visible": False}), [generous], 404, "visibility")
        self.no(ask("records.read", record={"visible": False}), [grant("read")], 404, "visibility")
        self.no(ask("records.archive", record={"visible": False}), [ARCHIVE], 404, "visibility")
        self.no(ask("actions.request", record={"visible": False}), [grant("run")], 404, "visibility")

    def test_workflow_state_and_open_work(self):  # P5
        self.no(ask("records.update", properties=["title"], record={"visible": True, "state": "done"}), [UPDATE], 409, "workflow")
        self.no(ask("records.archive", record={"visible": True, "open_run": True}), [ARCHIVE], 409, "workflow")
        self.no(ask("records.archive", entity="Owner"), [grant("records.archive", entities=["Owner"])], 403, "workflow")
        self.no(ask("records.archive", properties=["title"]), [ARCHIVE], 403, "properties")
        self.no(ask("actions.request", record={"visible": True, "open_run": True}), [grant("run")], 409, "workflow")
        self.no(ask("records.update", properties=["title"], links=["owns"]), [UPDATE], 403, "properties")
        linked = {**UPDATE, "links": ["owns"]}
        self.assertTrue(decide(ask("records.update", properties=["title"], links=["owns"]), [linked], MODEL)["allowed"])

    def test_who_never_does_what(self):  # P5
        robot = {"name": "app", "kind": "service", "roles": [], "reviewer_roles": ["lead"], "office": ["administrator"]}
        held = [{**g, "member": "app"} for g in (grant("review"), grant("configure"), ADMIN)]
        for operation in ("reviews.decide", "ontology.modify", "releases.manage", "permissions.administer", "data.administer"):
            self.no(ask(operation, identity=robot, review={"reviewer_roles": ["lead"]}), held, 403, "identity")
        for operation in ("actions.execute", "reviews.request"):  # the Engine's, inside a run: nobody is granted them
            for who in ({}, {"office": ["administrator"]}, robot):
                self.no(ask(operation, identity=who), [ADMIN, grant("run"), grant("review")], 403, "caller")
        lead = {"reviewer_roles": ["lead"]}
        self.no(ask("reviews.decide", identity=lead, review={"reviewer_roles": ["lead"], "requested_by": "pat"}), [grant("review")], 403, "separation")
        self.no(ask("reviews.decide", identity=lead, review={"reviewer_roles": ["chief"], "requested_by": "sam"}), [grant("review")], 403, "role")
        self.no(ask("reviews.decide", identity=lead, review={"reviewer_roles": ["lead"]}), [], 403, "grant")
        boss = {"office": ["administrator"]}
        self.no(ask("permissions.administer", identity=boss, target="pat"), [], 403, "separation")
        self.no(ask("releases.manage", identity=boss, approves_own=True), [], 403, "separation")
        self.no(ask("permissions.administer", target="sam"), [ADMIN], 403, "grant")       # no office by data permission
        self.no(ask("data.administer", identity=boss), [], 403, "grant")                  # no data permission by office
        self.no(ask("data.administer"), [grant("admin")], 403, "grant")                   # not acknowledged as unrestricted

    def test_no_right_implies_another(self):  # P6
        rights = {"records.read": grant("read"), "records.create": CREATE, "records.update": UPDATE, "records.archive": ARCHIVE,
                  "actions.request": grant("run"), "reviews.decide": grant("review"), "ontology.modify": grant("configure")}
        requests = {"records.read": ask("records.read"), "records.create": ask("records.create", properties=["title"]),
                    "records.update": ask("records.update", properties=["title"]), "records.archive": ask("records.archive"),
                    "actions.request": ask("actions.request"), "ontology.modify": ask("ontology.modify"),
                    "reviews.decide": ask("reviews.decide", identity={"reviewer_roles": ["lead"]},
                                          review={"reviewer_roles": ["lead"], "requested_by": "sam"})}
        for held, g in rights.items():
            allowed = sorted(op for op, request in requests.items() if decide(request, [g], MODEL)["allowed"])
            self.assertEqual(allowed, [held], held)


class InputTests(unittest.TestCase):
    def test_a_form_or_a_manifest_is_not_an_input(self):  # P7
        import re

        source = inspect.getsource(operation_policy).split('"""', 2)[2]
        read = set(re.findall(r'request(?:\.get\(|\[)"(\w+)"', source))  # everything the function reads of a request
        self.assertEqual(read, {"operation", "identity", "workspace", "use_case", "target", "approves_own", "entity",
                                "record", "review", "properties", "links", "sets_state"})
        for word in ("manifest", "screen", "header"):
            self.assertNotIn(word, source.lower(), word)
        with_form = ask("records.create", properties=["title"], form={"submit": True}, manifest={"grants": ["admin"]})
        self.assertEqual(decide(with_form, [], MODEL)["allowed"], False)
        self.assertEqual(decide(with_form, [CREATE], MODEL)["reason"], decide(ask("records.create", properties=["title"]), [CREATE], MODEL)["reason"])
