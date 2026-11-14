"""The Console's Configuration tab: an administrator sets the Claude key, model and effort on the engine."""

import json
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from autology.server import ApiError

from .test_ingest import TOKENS, service
from .test_platform import _Api

KEY = "sk-ant-api03-" + "x" * 40 + "WXYZ"


def fake_anthropic(behaviour="ok"):
    """A stand-in for the anthropic package: records the key the engine uses and answers model lookups."""
    mod = types.ModuleType("anthropic")
    mod.keys = []

    class APIStatusError(Exception):
        status_code = 500

    class AuthenticationError(APIStatusError):
        pass

    class PermissionDeniedError(APIStatusError):
        pass

    class NotFoundError(APIStatusError):
        pass

    class APIConnectionError(Exception):
        pass

    for cls in (APIStatusError, AuthenticationError, PermissionDeniedError, NotFoundError, APIConnectionError):
        setattr(mod, cls.__name__, cls)

    class Models:
        def retrieve(self, model):
            if behaviour == "ok":
                return types.SimpleNamespace(id=model, display_name="Claude Opus 5.5")
            raise {"auth": AuthenticationError, "missing": NotFoundError, "offline": APIConnectionError,
                   "nocreds": lambda: TypeError("Could not resolve authentication method")}[behaviour]()

    class Anthropic:
        def __init__(self, api_key=None):
            mod.keys.append(api_key)
            self.models = Models()

    mod.Anthropic = Anthropic
    return mod


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.secrets = Path(tempfile.mkdtemp()) / "nested" / "secrets.json"
        patcher = mock.patch.dict(os.environ, {"AUTOLOGY_SECRETS_FILE": str(self.secrets)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = str(Path(tempfile.mkdtemp()) / "engine.db")
        self.svc = service(automations={}, store=self.store)
        self.u = {x.name: x for x in self.svc.users}

    def restart(self):
        return service(automations={}, store=self.store)

    def test_only_admins(self):
        for call in (lambda u: self.svc.assistant_view(u), lambda u: self.svc.update_assistant(u, {"enabled": True}),
                     lambda u: self.svc.test_assistant(u)):
            with self.assertRaises(ApiError) as cm:
                call(self.u["hana"])
            self.assertEqual(cm.exception.status, 403)

    def test_defaults_and_validation(self):
        view = self.svc.assistant_view(self.u["admin"])
        self.assertEqual((view["enabled"], view["key"]["set"], view["model"]), (False, False, "claude-opus-5-5"))
        for body in ({"model": "gpt-9"}, {"effort": "extreme"}, {"api_key": "short"}, {"api_key": "sk-ant has spaces in it ok"},
                     {"enabled": "yes"}, {"colour": "blue"}):
            with self.subTest(body=body), self.assertRaises(ApiError) as cm:
                self.svc.update_assistant(self.u["admin"], body)
            self.assertEqual(cm.exception.status, 400)
        self.assertIsNone(self.svc.chat)

    def test_save_key_switches_the_assistant_on_and_never_echoes_the_key(self):
        view = self.svc.update_assistant(self.u["admin"], {"enabled": True, "model": "claude-sonnet-5-5",
                                                           "effort": "low", "api_key": KEY, "remember": True})
        self.assertEqual(view["key"], {"set": True, "hint": "…WXYZ", "remembered": True,
                                       "source": "remembered on this computer"})
        self.assertNotIn(KEY, json.dumps(view))
        self.assertIsNotNone(self.svc.chat)
        self.assertEqual((self.svc.chat.backend.model, self.svc.chat.backend.effort), ("claude-sonnet-5-5", "low"))
        hana = self.u["hana"]
        self.assertIs(self.svc.ontology_summary(hana)["assistant"], True)
        fake = fake_anthropic()
        with mock.patch.dict(sys.modules, {"anthropic": fake}):
            self.svc.chat.backend.client  # the engine builds its Claude client with the key from the Console
        self.assertEqual(fake.keys, [KEY])
        # the key is in the owner-only secrets file, not in the database or the access log
        self.assertEqual(json.loads(self.secrets.read_text())["anthropic_api_key"], KEY)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.secrets.stat().st_mode), 0o600)
        self.svc.store._db.execute("PRAGMA wal_checkpoint(FULL)")
        self.assertNotIn(KEY.encode(), Path(self.store).read_bytes())
        log = self.svc.store.access_log(limit=5)
        self.assertEqual((log[0]["kind"], log[0]["target"]), ("settings.assistant", "effort,enabled,model,remember,api_key"))
        self.assertFalse(any(KEY in json.dumps(r) for r in log))

    def test_survives_restart_only_when_remembered(self):
        self.svc.update_assistant(self.u["admin"], {"enabled": True, "api_key": KEY, "remember": True})
        again = self.restart()
        view = again.assistant_view(next(u for u in again.users if u.name == "admin"))
        self.assertEqual((view["enabled"], view["key"]["hint"]), (True, "…WXYZ"))
        self.assertIsNotNone(again.chat)
        again.update_assistant(next(u for u in again.users if u.name == "admin"), {"remember": False})
        self.assertNotIn("anthropic_api_key", json.loads(self.secrets.read_text()))
        third = self.restart()
        view = third.assistant_view(next(u for u in third.users if u.name == "admin"))
        self.assertEqual((view["enabled"], view["key"]["set"]), (True, False))  # settings kept, key forgotten

    def test_remove_key_and_switch_off(self):
        self.svc.update_assistant(self.u["admin"], {"enabled": True, "api_key": KEY, "remember": True})
        view = self.svc.update_assistant(self.u["admin"], {"clear_key": True, "enabled": False})
        self.assertFalse(view["key"]["set"])
        self.assertIsNone(self.svc.chat)
        self.assertNotIn("anthropic_api_key", json.loads(self.secrets.read_text()))

    def test_connection_check_spends_no_tokens(self):
        self.svc.update_assistant(self.u["admin"], {"enabled": True, "api_key": KEY, "remember": False})
        admin = self.u["admin"]
        cases = {"ok": (True, None), "auth": (False, "rejected the key"), "missing": (False, "not available"),
                 "offline": (False, "cannot reach Claude"), "nocreds": (False, "ant auth login")}
        for behaviour, (ok, text) in cases.items():
            with self.subTest(behaviour), mock.patch.dict(sys.modules, {"anthropic": fake_anthropic(behaviour)}):
                out = self.svc.test_assistant(admin)
            self.assertEqual(out["ok"], ok)
            if text:
                self.assertIn(text, out["error"])
        with mock.patch.dict(sys.modules, {"anthropic": None}):
            self.assertIn("pip install anthropic", self.svc.test_assistant(admin)["error"])

    def test_custom_backend_is_left_alone(self):
        from autology.settings import AssistantSettings, SettingsError

        settings = AssistantSettings(self.svc.store, {"backend": "my_module:my_backend"})
        self.assertTrue(settings.view()["custom_backend"])
        with self.assertRaises(SettingsError):
            settings.update({"enabled": False})

    def test_http_routes(self):
        api = _Api(self.svc)
        self.addCleanup(api.server.shutdown)
        self.assertEqual(api.call("GET", "/api/settings/assistant", TOKENS["hana"])[0], 403)
        status, view, _ = api.call("POST", "/api/settings/assistant", TOKENS["admin"],
                                   {"enabled": True, "api_key": KEY, "remember": False})
        self.assertEqual((status, view["key"]["hint"]), (200, "…WXYZ"))
        status, view, _ = api.call("GET", "/api/settings/assistant", TOKENS["admin"])
        self.assertEqual(status, 200)
        self.assertNotIn(KEY, json.dumps(view))
        status, onto, _ = api.call("GET", "/api/ontology", TOKENS["hana"])
        self.assertIs(onto["assistant"], True)


if __name__ == "__main__":
    unittest.main()
