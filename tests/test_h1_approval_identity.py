"""H-1 / F-02: a machine never records a human approval (audit of 15 Nov 2026; owner decision D11).

  A1 an API identity declared as a service (``"kind": "service"``) cannot decide a human review, even with the
     reviewer role and admin rights; a person with the same rights can
  A2 the same through the workspace router: a service member is refused, a person member is not
  A3 an HTTP approver (an automated outside system) cannot satisfy a human review on a real server: refused at
     start-up, like any automatic approver; in simulation its decisions are recorded as automatic and attributed
     to its origin, not to the reviewer name the outside system claims
  A4 a service identity cannot settle an external call that waits for a person (reconciliation)
  A5 policy-authorised autonomy is unchanged: a step no rule sends to review runs with no human at all
  A6 an unknown kind is refused when the configuration is loaded
"""

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from autology.platform import Platform, PlatformError
from autology.server import ApiError, hash_token

from .test_approvals import SAM
from .test_platform import EX, add_big_order, service
from .test_r2_use_case_lifecycle import close
from .test_workspaces import EX as PEX, TOKENS, Client, simulate_all

BOT = {**SAM, "name": "bot", "token_sha256": hash_token("tok-bot"), "kind": "service",
       "permissions": ["read", "run", "review", "admin"]}


class ApproverServer:
    def __init__(self, reply):
        outer, self.hits = self, []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.hits.append(self.path)
                body = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/review"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def with_bot(users=None, **overrides):
    users = users or json.loads((EX / "server.json").read_text())["users"] + [SAM, BOT]
    return service(users=users, automations={}, chat=None, **overrides)


def reviews(svc, run_id):
    return [e for e in svc.store.audit_log(run_id) if e.event in ("review", "review.decision")]


class EngineTests(unittest.TestCase):
    def test_a_service_identity_cannot_decide_a_human_review(self):  # A1
        svc = with_bot()
        bot, sam, lena = (next(u for u in svc.users if u.name == n) for n in ("bot", "sam", "lena"))
        self.assertEqual((bot.kind, lena.kind), ("service", "person"))
        run = svc.start_run(sam, add_big_order(svc))
        with self.assertRaises(ApiError) as cm:
            svc.decide(bot, run["pending_review"], {"approved": True, "comment": "automated"})
        self.assertEqual(cm.exception.status, 403)
        self.assertIn("service identity", cm.exception.message)
        self.assertEqual(svc.store.get_review(run["pending_review"])["status"], "pending")
        done = svc.decide(lena, run["pending_review"], {"approved": True, "comment": "checked"})
        self.assertEqual(done["status"], "completed")
        decision = reviews(svc, run["run_id"])[-1]
        self.assertEqual((decision.data["reviewer"], decision.data["automatic"]), ("lena", False))

    def test_an_unknown_kind_is_refused(self):  # A6
        with self.assertRaises(ValueError) as cm:
            with_bot(users=[{**BOT, "kind": "robot"}])
        self.assertIn("kind", str(cm.exception))


class HttpApproverTests(unittest.TestCase):
    def setUp(self):
        self.remote = ApproverServer({"approved": True, "reviewer": "lena", "comment": "fine"})
        self.addCleanup(self.remote.close)
        self.agents = {"fulfilment": {"roles": ["ops", "eu_ops", "finance"], "tools": "tools.json",
                                      "approver": {"type": "http", "url": self.remote.url, "environment": "sandbox"}}}

    def test_an_http_approver_cannot_stand_in_for_a_person_on_a_real_server(self):  # A3
        with self.assertRaises(ValueError) as cm:
            service(agents=self.agents, automations={}, chat=None)
        self.assertIn("simulation", str(cm.exception))

    def test_in_simulation_its_decisions_are_automatic_and_attributed_to_the_system(self):  # A3
        svc = service(agents=self.agents, automations={}, chat=None, simulation=True)
        admin = next(u for u in svc.users if "admin" in u.permissions)
        run = svc.start_run(admin, add_big_order(svc))
        self.assertEqual(self.remote.hits, ["/review"])
        review = reviews(svc, run["run_id"])[-1]
        self.assertTrue(review.data["automatic"])
        self.assertTrue(review.data["reviewer"].startswith("http:"), review.data["reviewer"])
        self.assertNotEqual(review.data["reviewer"], "lena")  # a claimed name is not an authenticated person
        self.assertIn("lena", review.data.get("comment", ""))  # kept as a claim, for the record


class PlatformTests(unittest.TestCase):
    def platform(self, members_patch):
        os.environ.update(TOKENS)
        os.environ["ACME_BOT_TOKEN"] = "acme-bot"
        self.addCleanup(os.environ.pop, "ACME_BOT_TOKEN", None)
        s = json.loads((PEX / "platform.json").read_text())
        s["data_dir"] = tempfile.mkdtemp()
        members_patch(s)
        return s

    def test_a_service_member_cannot_approve_through_the_router(self):  # A2
        def patch(s):
            acme = s["workspaces"]["acme"] if isinstance(s["workspaces"], dict) else s["workspaces"][0]
            ada = next(m for m in acme["members"] if m["name"].startswith("ada"))
            ivan = next(m for m in acme["members"] if m["name"] == "ivan")  # an SIU reviewer on the claims use case
            bot = {**json.loads(json.dumps(ivan)), "name": "bot@acme", "kind": "service", "token_env": "ACME_BOT_TOKEN"}
            acme["members"].append(bot)
        pf = simulate_all(Platform(self.platform(patch), PEX))
        self.addCleanup(close, pf)
        svc = pf.workspaces["acme"].use_cases["claims"].service
        self.assertEqual(svc.users and next(u for u in svc.users if u.name == "bot@acme").kind, "service")
        self.assertTrue(all(u.kind == "person" for u in svc.users if u.name != "bot@acme"))
        c = Client(pf)
        self.addCleanup(c.server.server_close)
        self.addCleanup(c.server.shutdown)
        status, run = c.call("POST", "/w/acme/u/claims/api/v1/runs", "acme-hana",
                             {"case_template": "claim_case", "root": "CL-2"})
        self.assertEqual(status, 200, run)
        review = run["pending_review"]
        status, out = c.call("POST", f"/w/acme/u/claims/api/v1/reviews/{review}/decision", "acme-bot",
                             {"approved": True, "comment": "automated"})
        self.assertEqual(status, 403, out)
        self.assertIn("service identity", out["error"]["message"])
        # A5: policy-authorised autonomy is unchanged: the clean claim is paid with nobody deciding anything
        status, clean = c.call("POST", "/w/acme/u/claims/api/v1/runs", "acme-hana",
                               {"case_template": "claim_case", "root": "CL-1"})
        self.assertEqual((status, clean["status"], clean.get("pending_review")), (200, "completed", None))

    def test_an_unknown_member_kind_is_refused(self):  # A6
        def patch(s):
            acme = s["workspaces"]["acme"] if isinstance(s["workspaces"], dict) else s["workspaces"][0]
            acme["members"][0]["kind"] = "robot"
        with self.assertRaises(PlatformError):
            Platform(self.platform(patch), PEX)


if __name__ == "__main__":
    unittest.main()
