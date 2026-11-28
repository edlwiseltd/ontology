"""Architect sprint, increment A: operational integrity before a real model is let near the system.

  I1 a stored run stays cancellable when its agent is no longer configured (renamed or removed by a later
     release): authorised, idempotent, audited; the run keeps its own record of the agent and the configuration
     it started on; it survives a restart; concurrent requests record one cancellation
  I2 a release brings no data with it. Sample records are loaded only by a workspace administrator's explicit,
     recorded request, only when an approved release is active and is what runs, only in Draft or Simulation;
     an existing record is never overwritten; loaded records are marked as samples
  I3 recovery evidence is recorded only by a rehearsal that succeeded (backup, verify, restore, load); readiness
     reports it for the configuration it covered and says so when the configuration changed; nothing is assumed
"""

import copy
import json
import threading

from .test_act2_release_configuration import WS
from .test_act3_persistent_simulation import ENGINE, UC, SimulationBase

SAMPLES = f"{UC}/sample-data"
READY = f"{UC}/readiness?target=production"


def recovery(report):
    return next(c for d in report["dimensions"] for c in d["conditions"] if c["id"] == "recovery_evidence")


class CancellationWithoutTheAgentTests(SimulationBase):
    def setUp(self):
        super().setUp()
        self.simulate()

    def rename_agent(self):
        """A second release whose only agent has another name: the first one's agent is gone."""
        changed = copy.deepcopy(self.configuration)
        changed["agents"]["planner_v2"] = changed["agents"].pop("disruption_agent")
        return self.released(None, changed, "the agent was renamed")

    def test_a_run_is_cancelled_after_its_agent_was_removed(self):  # I1
        _, run = self.begin("DEL-1002")
        self.assertEqual(run["status"], "awaiting_review")
        review_id = self.run_of(run["run_id"], self.zoe)["pending_review"]
        self.rename_agent()
        self.assertEqual(sorted(self.desk.agents), ["planner_v2"])
        cancel = f"{ENGINE}/runs/{run['run_id']}/cancel"
        # still authorised the same way
        self.assertEqual(self.call("POST", cancel, self.zoe, {"reason": "x"})[0], 403)
        self.assertEqual(self.call("POST", cancel, "nw-nadia", {"reason": "x"})[0], 404)
        self.assertEqual(self.call("POST", cancel, "acme-hana", {})[0], 400)
        status, out = self.call("POST", cancel, "acme-hana", {"reason": "its agent no longer exists"})
        self.assertEqual((status, out["status"]), (200, "cancelled"), out)
        # the run keeps its history: the agent that started it and the release it ran on
        self.assertEqual((out["agent"], out["configuration"], out["started_by"]),
                         ("disruption_agent", self.fingerprint, "hana"))
        self.assertEqual([s["action"] for s in out["steps"]], ["assess_impact", "compare_alternatives"])
        entries = self.events(run["run_id"])  # the chain verifies and names who stopped it and why
        self.assertEqual([(e["data"]["by"], e["data"]["reason"]) for e in entries if e["event"] == "run.cancelled"],
                         [("hana", "its agent no longer exists")])
        self.assertEqual(self.desk.store.get_review(review_id)["status"], "cancelled")
        # idempotent: asking again answers with the same run and records nothing more
        status, again = self.call("POST", cancel, "acme-hana", {"reason": "once more"})
        self.assertEqual((status, again["status"], again["escalation"]["reason"]),
                         (200, "cancelled", "cancelled by hana: its agent no longer exists"))
        self.assertEqual(len(self.events(run["run_id"])), len(entries))
        # a run that ended otherwise is still refused, and a stale run cannot be continued instead
        done = self.begin("DEL-1001")[1]
        self.assertEqual(self.call("POST", f"{ENGINE}/runs/{done['run_id']}/cancel", "acme-hana", {"reason": "late"})[0], 409)

    def test_cancellation_survives_a_restart_and_a_waiting_orphan_is_cancelled_after_one(self):  # I1
        _, first = self.begin("DEL-1002")
        self.rename_agent()
        self.start()  # the platform stops and starts again on the same data
        self.assertEqual(self.run_of(first["run_id"])["status"], "awaiting_review")
        status, out = self.call("POST", f"{ENGINE}/runs/{first['run_id']}/cancel", "acme-hana", {"reason": "after a restart"})
        self.assertEqual((status, out["status"], out["agent"]), (200, "cancelled", "disruption_agent"), out)
        self.start()
        again = self.run_of(first["run_id"])
        self.assertEqual((again["status"], again["audit_verified"]), ("cancelled", True))
        self.assertEqual(self.call("GET", f"{ENGINE}/reviews", self.zoe)[1]["items"], [])

    def test_concurrent_cancellations_record_one(self):  # I1
        _, run = self.begin("DEL-1002")
        self.rename_agent()
        results = []

        def ask(n):
            results.append(self.call("POST", f"{ENGINE}/runs/{run['run_id']}/cancel", "acme-hana", {"reason": f"request {n}"}))
        threads = [threading.Thread(target=ask, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual([(s, o["status"]) for s, o in results], [(200, "cancelled")] * 6, results)
        cancelled = [e for e in self.events(run["run_id"]) if e["event"] == "run.cancelled"]
        self.assertEqual(len(cancelled), 1)
        self.assertEqual({o["escalation"]["reason"] for _, o in results}, {f"cancelled by hana: {cancelled[0]['data']['reason']}"})


class SampleDataTests(SimulationBase):
    """SimulationBase has already loaded the samples once, explicitly; these tests look at that act."""

    def events_of(self, name):
        return [e for e in self.call("GET", f"{WS}/members")[1]["history"] if e["event"] == name]

    def test_loading_is_explicit_recorded_and_never_overwrites(self):  # I2
        loaded = self.events_of("sample_data_loaded")
        self.assertEqual([(e["by"], e["reason"], e["data"]["use_case"], e["data"]["release"], e["data"]["loaded"],
                           e["data"]["configuration"]) for e in loaded],
                         [("ada@acme", "records to rehearse with", "desk", self.release, 12, self.fingerprint)])
        status, state = self.call("GET", SAMPLES)
        self.assertEqual((status, state["available"], len(state["loaded"]), state["loadable"], state["release"]),
                         (200, 12, 12, False, self.release))
        self.assertEqual(len(self.desk.store.sample_records()), 12)  # each one is marked as a sample
        self.assertEqual({r["loaded_by"] for r in self.desk.store.sample_records().values()}, {"ada@acme"})
        # asking again loads nothing; a record someone changed is left as it is
        self.simulate()
        self.assertEqual(self.begin("DEL-1001")[1]["status"], "completed")
        before = self.record("DEL-1001")
        status, out = self.call("POST", SAMPLES, body={"reason": "again"})
        self.assertEqual((status, out["just_loaded"], len(out["skipped"])), (200, [], 12), out)
        self.assertEqual(self.record("DEL-1001"), before)
        self.assertEqual(before["response"], "delay_accepted")

    def test_who_may_load_and_when(self):  # I2
        for token, expected in ((self.zoe, 403), ("acme-hana", 403), (self.bot, 404), ("nw-nadia", 404), ("acme-maria", 404)):
            self.assertEqual(self.call("POST", SAMPLES, token, {"reason": "x"})[0], expected, token)
        self.assertEqual(self.call("POST", SAMPLES, body={})[0], 400)  # a reason is required
        self.assertEqual(self.call("GET", SAMPLES, "acme-hana")[1]["may_load"], False)
        self.assertEqual(self.call("GET", SAMPLES, "nw-nadia")[0], 404)
        # a published configuration that is not released yet brings nothing, and nothing can be loaded for it
        more = copy.deepcopy(self.configuration)
        more["sample_data"]["instances"].append({**more["sample_data"]["instances"][2], "id": "DEL-2001"})
        more["sample_data"]["links"] += [["SUP-NORTH", "supplies", "DEL-2001"], ["ALT-1001", "covers", "DEL-2001"]]
        self.assertEqual(self.publish(self.draft(None, more))[0], 200)
        status, out = self.call("POST", SAMPLES, body={"reason": "the new record"})
        self.assertEqual(status, 409, out)
        self.assertIn("approved release is active and is what runs", out["error"]["message"])
        self.assertEqual(self.call("GET", SAMPLES)[1]["loadable"], False)
        self.assertEqual(self.desk.store.count_instances(), 12)
        # once that configuration is released, only what is new is loaded
        number = self.propose("one more sample")
        self.assertEqual(self.approve(number)[0], 200)
        self.assertEqual(self.activate(number)[0], 200)
        self.assertEqual(self.call("GET", SAMPLES)[1]["loadable"], True)
        status, out = self.call("POST", SAMPLES, body={"reason": "the new record"})
        self.assertEqual((status, out["just_loaded"], len(out["skipped"])), (200, ["DEL-2001"], 12), out)
        self.assertEqual(len(self.events_of("sample_data_loaded")), 2)
        # not in Pilot: sample records are for rehearsal
        uc = self.pf.workspaces["acme"].use_cases["desk"]
        self.pf.lifecycle.append("acme", "desk", "simulation", "pilot", "ada@acme", "pilot granted (recorded for the test)",
                                 uc.service.ontology.fingerprint, [])
        status, out = self.call("POST", SAMPLES, body={"reason": "in pilot"})
        self.assertEqual(status, 409, out)
        self.assertIn("pilot", out["error"]["message"])

    def test_a_use_case_without_samples_and_one_configured_in_files(self):  # I2
        claims = f"{WS}/use-cases/claims/sample-data"
        status, state = self.call("GET", claims)
        self.assertEqual((status, state["available"], state["loadable"]), (200, 0, False))
        self.assertEqual(self.call("POST", claims, body={"reason": "x"})[0], 409)


class RecoveryEvidenceTests(SimulationBase):
    def test_evidence_exists_only_after_a_rehearsal_that_succeeded(self):  # I3
        first = recovery(self.call("GET", READY)[1])
        self.assertEqual((first["measured"], first["passed"], first["blocking"]), (False, None, True))
        self.assertIn("no recovery evidence", first["detail"])
        for token, expected in (("acme-hana", 403), ("acme-maria", 403), (self.bot, 403), ("nw-nadia", 404)):
            self.assertEqual(self.call("POST", f"{WS}/recovery-drill", token, {"reason": "x"})[0], expected, token)
        self.assertEqual(self.call("POST", f"{WS}/recovery-drill", body={})[0], 400)
        status, out = self.call("POST", f"{WS}/recovery-drill", body={"reason": "quarterly rehearsal"})
        self.assertEqual(status, 200, out)
        self.assertEqual((out["recorded"], out["steps"]), (True, ["backup", "verify", "restore", "load"]))
        self.assertEqual(out["use_cases"]["desk"], {"configuration": self.fingerprint, "reproduces_what_runs": True})
        self.assertEqual(sorted(out["use_cases"]), ["claims", "desk", "orders"])
        # GAP-067: a backup carries the agents configured in Studio, not only the model beside them
        import tempfile
        from pathlib import Path

        from autology import recovery as module

        folder = Path(tempfile.mkdtemp()) / "backup"
        module.backup(self.pf.data_dir, folder)
        self.assertEqual((folder / "acme" / "desk" / "solution.json").read_bytes(),
                         (self.home / "solution.json").read_bytes())
        self.assertGreaterEqual(out["counts"]["stores"], 3)
        after = recovery(self.call("GET", READY)[1])
        self.assertEqual((after["measured"], after["passed"], after["blocking"]), (True, True, False))
        self.assertIn("is what runs", after["detail"])
        self.assertIn("recovery rehearsed", " ".join(after["evidence"]))
        events = [e for e in self.call("GET", f"{WS}/members")[1]["history"] if e["event"] == "recovery_rehearsed"]
        self.assertEqual([(e["by"], e["reason"]) for e in events], [("ada@acme", "quarterly rehearsal")])
        # the rehearsal left the running platform as it was, and production is still not available
        self.assertEqual(self.desk.configuration_fingerprint, self.fingerprint)
        self.assertFalse(self.call("GET", READY)[1]["production"]["authorised"])
        # the configuration changes: the evidence is for another configuration, and readiness says so
        changed = copy.deepcopy(self.configuration)
        changed["agents"]["disruption_agent"]["purpose"] = "Handles delayed deliveries"
        self.released(None, changed, "wording")
        stale = recovery(self.call("GET", READY)[1])
        self.assertEqual((stale["measured"], stale["passed"], stale["blocking"]), (True, False, True))
        self.assertIn("rehearse again", stale["detail"])
        self.assertIn(self.fingerprint[:12], stale["detail"])

    def test_a_rehearsal_that_fails_records_nothing(self):  # I3
        from unittest import mock

        from autology import recovery as module

        with mock.patch.object(module, "verify", side_effect=module.RecoveryError("the backup does not verify: test")):
            status, out = self.call("POST", f"{WS}/recovery-drill", body={"reason": "will fail"})
        self.assertEqual(status, 409, out)
        self.assertIn("no evidence was recorded", out["error"]["message"])
        self.assertFalse(recovery(self.call("GET", READY)[1])["measured"])
        self.assertEqual([e for e in self.call("GET", f"{WS}/members")[1]["history"] if e["event"] == "recovery_rehearsed"], [])
        status, out = self.call("POST", f"{WS}/recovery-drill", body={"reason": "now it works"})  # and can be retried
        self.assertEqual(status, 200, json.dumps(out)[:300])


if __name__ == "__main__":
    import unittest

    unittest.main()
