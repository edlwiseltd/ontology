"""Tier 2: generated typed client libraries (Python and TypeScript)."""

import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from autology import Ontology
from autology.__main__ import main as cli
from autology.sdk import _free, _pascal, _snake, generate, names

from .helpers import ROOT
from .test_platform import CASE, EX, TOKENS, _Api, service

ONTOLOGIES = [EX / "ontology.json", ROOT / "examples/scheduling/ontology.json",
              ROOT / "examples/manufacturing/enterprise.json", ROOT / "examples/customer_onboarding/ontology.json",
              ROOT / "examples/care_referral/ontology.json"]
NODE, TSC = shutil.which("node"), shutil.which("tsc")


def load_module(code: str, name: str):
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(code)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class GeneratorTests(unittest.TestCase):
    def test_python_clients_import_for_every_example(self):
        for i, path in enumerate(ONTOLOGIES):
            onto = Ontology.load(path)
            with self.subTest(onto.ref):
                mod = load_module(generate(onto, "python"), f"client_{i}")
                self.assertEqual(mod.ONTOLOGY_FINGERPRINT, onto.fingerprint)
                self.assertTrue(hasattr(mod.AutologyClient, "check_compatibility"))

    def test_names_and_collisions(self):
        self.assertEqual((_snake("WorkOrder"), _snake("CQ-01"), _snake("class"), _snake("1st")),
                         ("work_order", "cq_01", "class_", "n_1st"))
        self.assertEqual(_pascal("fulfil_contract"), "FulfilContract")
        taken = {"get_run"}
        self.assertEqual(_free("get_run", taken, "_object"), "get_run_object")
        doc = json.loads((EX / "ontology.json").read_text())
        doc["entities"]["Run"] = {"states": ["open"], "attributes": {"class": "string", "odd-name": "number",
                                                                      "blob": "json"}}
        onto = Ontology.from_dict(doc)
        helpers = names(onto)
        self.assertIn("get_run_object", helpers["python"])
        self.assertIn("getRunObject", helpers["typescript"])
        self.assertIn("ask_cq_01", helpers["python"])
        self.assertIn("runFulfilContract", helpers["typescript"])
        mod = load_module(generate(onto, "python"), "client_collide")
        self.assertIn("odd-name", mod.RunAttributes.__annotations__)  # functional TypedDict for odd keys
        self.assertIn('"blob"?: Json | null;', generate(onto, "typescript"))
        with self.assertRaises(ValueError):
            generate(onto, "cobol")

    @unittest.skipUnless(TSC, "TypeScript compiler not installed")
    def test_typescript_clients_typecheck_strictly(self):
        tmp = Path(tempfile.mkdtemp())
        files = []
        for i, path in enumerate(ONTOLOGIES):
            f = tmp / f"client{i}.ts"
            f.write_text(generate(Ontology.load(path), "typescript"))
            files.append(str(f))
        proc = subprocess.run([TSC, "--strict", "--noEmit", "--target", "es2022", "--lib", "es2022,dom", *files],
                              capture_output=True, text=True, timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class RoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = service(automations={})
        cls.api = _Api(cls.svc)

    @classmethod
    def tearDownClass(cls):
        cls.api.server.shutdown()

    def test_python_client_against_the_server(self):
        status, code, _ = self.api.call("GET", "/api/sdk/python", "olivia")
        self.assertEqual(status, 200)
        mod = load_module(code, "live_client")
        olivia = mod.AutologyClient(self.api.base, TOKENS["olivia"])
        lena = mod.AutologyClient(self.api.base, TOKENS["lena"])
        self.assertIsNone(olivia.check_compatibility())
        self.assertEqual([o["id"] for o in olivia.list_order()], ["O-1", "O-2"])  # EU order hidden
        self.assertEqual(olivia.get_customer("C-1")["attributes"]["credit_limit"], "***redacted***")
        with self.assertRaises(mod.AutologyApiError) as cm:
            olivia.get_order("C-1")
        self.assertEqual(cm.exception.status, 404)
        with self.assertRaises(mod.AutologyApiError) as cm:
            olivia.get_order("O-3")
        self.assertEqual(cm.exception.status, 404)
        self.assertEqual(olivia.ask_cq_01(), ["O-1", "O-2"])
        run = olivia.run_fulfil_contract(CASE, case_id="sdk")
        self.assertEqual(run["status"], "awaiting_review")
        review = lena.list_reviews()[0]
        done = lena.decide(review["review_id"], True, "ok from the SDK")
        self.assertEqual(done["status"], "completed")
        self.assertEqual(olivia.get_run(run["run_id"])["status"], "completed")
        self.assertIn("compliance", olivia.report().lower())
        self.assertEqual(olivia.automations(), [])
        self.assertEqual(lena.notifications()[0]["kind"], "review")
        sid = olivia.create_scenario("sdk", [{"op": "set", "id": "O-1", "attributes": {"amount": 1}}])["scenario_id"]
        self.assertEqual(olivia.compare_scenario(sid)["diff"]["changed"]["O-1"]["amount"], [9000, 1])
        self.assertEqual(olivia.discard_scenario(sid)["status"], "discarded")
        stale = mod.AutologyClient(self.api.base + "/", TOKENS["olivia"])
        mod.ONTOLOGY_FINGERPRINT = "other"
        self.assertIn("fingerprint differs", stale.check_compatibility())
        with self.assertRaises(mod.AutologyApiError) as cm:
            mod.AutologyClient(self.api.base, "wrong").me()
        self.assertEqual(cm.exception.status, 401)
        self.assertEqual(self.api.call("GET", "/api/sdk/cobol", "olivia")[0], 404)
        self.assertEqual(self.api.call("GET", "/api/sdk/python")[0], 401)

    @unittest.skipUnless(NODE, "Node.js not installed")
    def test_typescript_client_against_the_server(self):
        _, code, _ = self.api.call("GET", "/api/sdk/typescript", "olivia")
        tmp = Path(tempfile.mkdtemp())
        (tmp / "client.ts").write_text(code)
        (tmp / "main.ts").write_text(f"""
import {{ AutologyClient, AutologyApiError }} from "./client.ts";
const olivia = new AutologyClient({json.dumps(self.api.base)}, {json.dumps(TOKENS["olivia"])});
const out: Record<string, unknown> = {{}};
out.compatible = await olivia.checkCompatibility();
out.orders = (await olivia.listOrder()).map((o) => o.id);
out.credit = (await olivia.getCustomer("C-1")).attributes.credit_limit;
out.answer = await olivia.askCq01();
try {{ await olivia.getOrder("O-3"); }} catch (e) {{ out.hidden = e instanceof AutologyApiError ? e.status : -1; }}
const run = await olivia.runFulfilContract({json.dumps(CASE)}, {{ caseId: "ts" }});
out.status = run.status;
console.log(JSON.stringify(out));
""")
        proc = subprocess.run([NODE, "--experimental-strip-types", "--no-warnings", str(tmp / "main.ts")],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(out, {"compatible": None, "orders": ["O-1", "O-2"], "credit": "***redacted***",
                               "answer": ["O-1", "O-2"], "hidden": 404, "status": "awaiting_review"})


class SdkCliTests(unittest.TestCase):
    def test_cli(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli(["sdk", str(EX / "ontology.json"), "--lang", "typescript"]), 0)
        self.assertIn("export class AutologyClient", out.getvalue())
        target = Path(tempfile.mkdtemp()) / "client.py"
        with redirect_stderr(io.StringIO()):
            self.assertEqual(cli(["sdk", str(EX / "ontology.json"), "--out", str(target)]), 0)
        self.assertIn("class AutologyClient", target.read_text())


if __name__ == "__main__":
    unittest.main()
