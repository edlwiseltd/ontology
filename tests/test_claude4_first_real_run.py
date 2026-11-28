"""What the first run with a real model found between a proposal and a stored run (17 November 2026).

The model proposed a case that spans several relationships (a turnaround, its conflicts, their recovery options,
the options' team assignments) and four agents. Two things then stood between that proposal and a run in Studio:

  J1 no sample record was produced for an entity more than one relationship away from the root, and none at all
     when the starting configuration came from the agents the architect described: with no record, no run
  J2 (Studio, ``tests/runs.test.ts``) the runs screen named neither the agent nor the goal, which the engine
     needs as soon as there is more than one

No provider is contacted here: the model below is written by hand in the shape the real proposal had.
"""

import unittest

from autology import solution as solutions
from autology.graph import KnowledgeGraph, build_case
from autology.ontology import Ontology
from autology.simulation import sample_case

MODEL = {
    "name": "ground", "version": "0.1.0",
    "entities": {
        "Turnaround": {"states": ["scheduled", "delayed", "completed"], "attributes": {"delay_minutes": "number"}},
        "Conflict": {"states": ["open", "resolved"], "attributes": {"kind": "string"}},
        "Option": {"states": ["proposed", "approved", "executed"], "attributes": {"cost_eur": "number"}},
        "Assignment": {"states": ["planned", "confirmed"], "attributes": {}},
        "Team": {"states": ["available", "assigned"], "attributes": {}},
        "Record": {"states": ["recorded"], "attributes": {}},
    },
    "relationships": [
        {"from": "Turnaround", "to": "Conflict", "type": "conflicts", "cardinality": "1..*"},
        {"from": "Conflict", "to": "Option", "type": "options", "cardinality": "1..*"},
        {"from": "Option", "to": "Assignment", "type": "assignments", "cardinality": "1..*"},
        {"from": "Assignment", "to": "Team", "type": "team", "cardinality": "1"},
        {"from": "Record", "to": "Turnaround", "type": "about", "cardinality": "1"},
    ],
    "actions": {
        "mark_delayed": {"description": "d", "capability": "ops.mark", "requires": ["Turnaround.status == 'scheduled'"],
                         "effects": {"Turnaround": {"status": "delayed"}}, "side_effect": "none"},
        "approve_option": {"description": "d", "capability": "ops.approve", "requires": ["Option.status == 'proposed'"],
                           "effects": {"Option": {"status": "approved"}}, "side_effect": "none"},
    },
    "rules": [{"id": "R1", "type": "human_review", "description": "a manager approves costly options",
               "action": "approve_option", "reviewer": "manager", "when": "Option.cost_eur > 2000"}],
    "goals": {"recovered": {"description": "d", "target": "Turnaround.status == 'completed'"}},
    "case_templates": {"delayed_turnaround": {"description": "d", "root": "Turnaround", "entities": {
        "Turnaround": "self", "Conflict": "conflicts", "Option": "conflicts.options",
        "Assignment": "conflicts.options.assignments", "Team": "conflicts.options.assignments.team",
        "Record": "^about"}}},
}


class SampleRecordTests(unittest.TestCase):
    def setUp(self):
        self.onto = Ontology.from_dict(MODEL)
        self.sample = sample_case(self.onto, MODEL)

    def test_one_linked_record_for_every_entity_of_the_case(self):  # J1
        data = solutions.sample_records(self.onto, self.sample)
        self.assertEqual(sorted(i["type"] for i in data["instances"]), sorted(MODEL["entities"]))
        ids = {i["type"]: i["id"] for i in data["instances"]}
        self.assertEqual(len(set(ids.values())), 6)
        self.assertEqual(sorted(data["links"]), sorted([
            [ids["Turnaround"], "conflicts", ids["Conflict"]], [ids["Conflict"], "options", ids["Option"]],
            [ids["Option"], "assignments", ids["Assignment"]], [ids["Assignment"], "team", ids["Team"]],
            [ids["Record"], "about", ids["Turnaround"]]]))  # a step against its direction links the other way round
        option = next(i for i in data["instances"] if i["type"] == "Option")
        self.assertEqual((option["status"], option["cost_eur"]), ("proposed", 2001))  # at the review's threshold
        # the records fit the model, and a case read from them along the template is complete
        suggested = solutions.suggest(MODEL, self.sample)
        self.assertEqual(suggested["sample_data"], data)
        self.assertEqual(solutions.check(suggested, MODEL)[0], [])
        graph = KnowledgeGraph.from_dict(self.onto, {"instances": [dict(i) for i in data["instances"]],
                                                     "links": [tuple(link) for link in data["links"]]})
        case, sources = build_case(graph, "delayed_turnaround", ids["Turnaround"])
        self.assertEqual(sorted(case), sorted(MODEL["entities"]))  # every entity of the template was reached
        self.assertEqual(case["Option"]["cost_eur"], 2001)

    def test_a_sample_can_start_the_work_and_never_claims_a_record_that_exists(self):  # J1
        """The first stored run of the model's proposal escalated at once: its turnaround had a delay of 0 and the
        model's first action needs 10 minutes. And a corrected sample would not have been loaded: same identifier."""
        model = {**MODEL, "entities": {**MODEL["entities"], "Turnaround": {
            "states": ["scheduled", "delayed", "completed"], "attributes": {"delay_minutes": "integer", "gate": "integer"}}}}
        model["actions"] = {**MODEL["actions"], "mark_delayed": {
            **MODEL["actions"]["mark_delayed"], "requires": ["Turnaround.status == 'scheduled' and Turnaround.delay_minutes >= 10"]},
            "review_gate": {"description": "d", "capability": "ops.gate", "requires": ["Turnaround.gate < 40 and Option.cost_eur <= 2000"],
                            "effects": {}, "side_effect": "none"}}
        onto = Ontology.from_dict(model)
        case = sample_case(onto, model)
        self.assertEqual(case["Turnaround"]["delay_minutes"], 10)  # the first action's precondition is met
        self.assertEqual(case["Turnaround"]["gate"], 0)  # an upper bound is met by the default already
        self.assertEqual(case["Option"]["cost_eur"], 2001)  # the review's threshold still wins: it is what is rehearsed
        first = solutions.sample_records(onto, case)
        again = solutions.sample_records(onto, case, taken=[i["id"] for i in first["instances"]])
        self.assertEqual(sorted(i["id"] for i in first["instances"]),
                         ["ASSIGNME-1", "CONFLICT-1", "OPTION-1", "RECORD-1", "TEAM-1", "TURNAROU-1"])
        self.assertEqual(sorted(i["id"] for i in again["instances"]),
                         ["ASSIGNME-2", "CONFLICT-2", "OPTION-2", "RECORD-2", "TEAM-2", "TURNAROU-2"])
        self.assertTrue(all(a.endswith("-2") and b.endswith("-2") for a, _, b in again["links"]))
        self.assertEqual(solutions.check({"agents": {}, "sample_data": again}, model)[0], [])

    def test_no_template_no_records_and_colliding_names_stay_apart(self):  # J1
        bare = {k: v for k, v in MODEL.items() if k != "case_templates"}
        self.assertIsNone(solutions.sample_records(Ontology.from_dict(bare), sample_case(Ontology.from_dict(bare), bare)))
        self.assertNotIn("sample_data", solutions.suggest(bare, self.sample))
        twins = {"name": "t", "version": "0.1.0",
                 "entities": {"TeamAssignmentA": {"states": ["s"], "attributes": {}},
                              "TeamAssignmentB": {"states": ["s"], "attributes": {}}},
                 "relationships": [{"from": "TeamAssignmentA", "to": "TeamAssignmentB", "type": "next", "cardinality": "1"}],
                 "case_templates": {"c": {"description": "d", "root": "TeamAssignmentA",
                                          "entities": {"TeamAssignmentA": "self", "TeamAssignmentB": "next"}}}}
        onto = Ontology.from_dict(twins)
        data = solutions.sample_records(onto, sample_case(onto, twins))
        self.assertEqual(sorted(i["id"] for i in data["instances"]), ["TEAMASSI-1", "TEAMASSI-2"])
        self.assertEqual(data["links"], [["TEAMASSI-1", "next", "TEAMASSI-2"]])


class SharedCapabilityTests(unittest.TestCase):
    """J3: the real model gave six actions one capability. Studio assigns a tool to each action; the engine
    chooses by capability. The audit trail of the first runs named a tool after another action."""

    def setUp(self):
        self.model = {**MODEL, "actions": {
            **MODEL["actions"],
            "detect": {"description": "d", "capability": "planning", "requires": ["Conflict.status == 'open'"],
                       "effects": {}, "side_effect": "none"},
            "assess": {"description": "d", "capability": "planning", "requires": ["Conflict.status == 'open'"],
                       "effects": {"Conflict": {"status": "resolved"}}, "side_effect": "none"}}}

    def agent(self, **tools):
        return {"agents": {"a": {"purpose": "p", "responsibilities": [], "roles": [], "goals": ["recovered"],
                                 "autonomy": {"mode": "policy"},
                                 "tools": [{"action": action, **spec} for action, spec in tools.items()]}}}

    def test_actions_of_one_capability_share_one_tool_named_after_it(self):
        same = self.agent(mark_delayed={"tool": "simulated.succeed"}, detect={"tool": "simulated.succeed"},
                          assess={"tool": "simulated.succeed"})
        problems, compiled = solutions.check(same, self.model)
        self.assertEqual(problems, [])
        tools = compiled["agents"]["a"]["tools"]["tools"]
        self.assertEqual([(t["name"], t["capability"]) for t in tools], [("a.mark_delayed", "ops.mark"), ("a.planning", "planning")])
        self.assertIn("for detect, assess", tools[1]["description"])
        self.assertEqual(len({t["capability"] for t in tools}), len(tools))  # the engine's choice is never ambiguous

    def test_different_behaviour_under_one_capability_is_refused(self):
        mixed = self.agent(detect={"tool": "simulated.succeed"}, assess={"tool": "simulated.fail", "error": "outage"})
        problems, compiled = solutions.check(mixed, self.model)
        self.assertIsNone(compiled)
        self.assertEqual(len(problems), 1)
        self.assertIn("detect, assess share the capability 'planning'", problems[0]["message"])
        # a configuration without shared capabilities compiles exactly as before
        plain = self.agent(mark_delayed={"tool": "simulated.succeed"}, approve_option={"tool": "simulated.succeed"})
        names = [t["name"] for t in solutions.check(plain, self.model)[1]["agents"]["a"]["tools"]["tools"]]
        self.assertEqual(names, ["a.mark_delayed", "a.approve_option"])


if __name__ == "__main__":
    unittest.main()
