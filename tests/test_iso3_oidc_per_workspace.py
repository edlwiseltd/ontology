"""ISO-3: each workspace may sign people in with its own company identity provider; a token from one
workspace's provider is refused by every other workspace."""

import json
import os
import tempfile
import unittest

from autology.platform import Platform

from .test_oidc import OIDC, FakeIdP
from .test_workspaces import EX, TOKENS, Client, platform


class OidcPerWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.update(TOKENS)
        cls.acme_idp, cls.nw_idp = FakeIdP(), FakeIdP()
        spec = json.loads((EX / "platform.json").read_text())
        spec["data_dir"] = tempfile.mkdtemp()
        spec["workspaces"]["acme"]["oidc"] = {"issuer": cls.acme_idp.issuer, **OIDC}
        spec["workspaces"]["northwind"]["oidc"] = {"issuer": cls.nw_idp.issuer, **OIDC}
        cls.pf = Platform(spec, EX)
        cls.c = Client(cls.pf)

    @classmethod
    def tearDownClass(cls):
        cls.c.server.shutdown()
        cls.acme_idp.server.shutdown()
        cls.nw_idp.server.shutdown()

    def test_a_workspace_accepts_its_own_providers_tokens(self):
        status, me = self.c.call("GET", "/w/acme/u/claims/api/me", self.acme_idp.token())
        self.assertEqual((status, me["name"], me["reviewer_roles"]), (200, "nora", ["claims_manager"]))
        status, me = self.c.call("GET", "/w/northwind/u/claims/api/me", self.nw_idp.token())
        self.assertEqual(status, 200)

    def test_a_token_from_another_workspaces_provider_is_refused(self):
        status, body = self.c.call("GET", "/w/northwind/u/claims/api/me", self.acme_idp.token())
        self.assertEqual(status, 401)
        status, _ = self.c.call("GET", "/w/northwind/u/claims/api/objects?type=Claim", self.acme_idp.token())
        self.assertEqual(status, 401)
        status, _ = self.c.call("GET", "/w/acme/u/orders/api/me", self.nw_idp.token())
        self.assertEqual(status, 401)

    def test_a_workspace_without_company_sign_in_refuses_any_jwt(self):
        plain = platform()  # no oidc in either workspace
        client = Client(plain)
        self.addCleanup(client.server.shutdown)
        self.assertEqual(client.call("GET", "/w/acme/u/claims/api/me", self.acme_idp.token())[0], 401)

    def test_member_tokens_still_work_and_names_cannot_be_taken_over(self):
        self.assertEqual(self.c.call("GET", "/w/acme/u/claims/api/me", "acme-hana")[0], 200)
        # a company account named like a member of that workspace is refused, never mapped onto the member
        status, _ = self.c.call("GET", "/w/acme/u/claims/api/me", self.acme_idp.token(preferred_username="hana"))
        self.assertEqual(status, 401)

    def test_a_use_cases_own_oidc_setting_never_applies(self):
        cfg_oidc = [uc.service.oidc for ws in self.pf.workspaces.values() for uc in ws.use_cases.values()]
        self.assertTrue(all(p is not None for p in cfg_oidc))
        issuers = {ws: {uc.service.oidc.issuer for uc in w.use_cases.values()} for ws, w in self.pf.workspaces.items()}
        self.assertEqual(issuers, {"acme": {self.acme_idp.issuer}, "northwind": {self.nw_idp.issuer}})


if __name__ == "__main__":
    unittest.main()
