"""Bring the three synthetic use cases of examples/domains to "released, in Simulation, with records and grants",
through the platform's HTTP API, so that the Application Builder's browser tests start from a released solution.

It makes the same calls as the cross-domain tests (tests/test_xdom1_cross_domain.Journey): describe, answer,
accept, configure, publish and approve by a second person, activate, load the synthetic records, move to
Simulation, grant an operator and a reviewer. The third domain has no template: its model is saved as it is.

    python e2e/prepare_apps.py http://127.0.0.1:8703
"""
import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tests.test_app1_application_builder import venue  # noqa: E402
from tests.test_xdom1_cross_domain import DOMAINS, Journey  # noqa: E402


class Http:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def call(self, method, path, token=None, body=None):
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
        request = urllib.request.Request(self.base + path, method=method, headers=headers,
                                         data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(request, timeout=60) as answer:
                return answer.status, json.loads(answer.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")


def main(base):
    client, check = Http(base), unittest.TestCase()
    for ws in DOMAINS:
        Journey(check, client, ws).design().release()
        print(f"prepared {ws}")
    venue(check, client)
    print("prepared venues")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8703")
