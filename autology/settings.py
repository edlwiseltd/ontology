"""Assistant settings an administrator changes at run time, from the Console's Configuration tab.

* **The Claude key never reaches the database or the browser.** It is held in the engine's memory and, when the
  administrator ticks "remember", written to a per-user secrets file outside the project (``%APPDATA%\\Autology``
  on Windows, ``~/.config/autology`` elsewhere, or ``AUTOLOGY_SECRETS_FILE``), created readable by its owner only.
  The API only ever reports whether a key is set, where it comes from and its last four characters.
* Model, effort and on/off are not secret: they are kept in the store's ``meta`` table, so they survive restarts
  and backups, and override the server config's ``chat`` section once an administrator has saved them.
* Without a key entered here, the Claude SDK finds credentials the usual way: ``ANTHROPIC_API_KEY``,
  ``ANTHROPIC_AUTH_TOKEN``, or an ``ant auth login`` profile.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
META_KEY = "assistant_settings"
SECRET_NAME = "anthropic_api_key"


class SettingsError(ValueError):
    pass


def default_secrets_path() -> Path:
    explicit = os.environ.get("AUTOLOGY_SECRETS_FILE")
    if explicit:
        return Path(explicit)
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Autology" / "secrets.json"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autology" / "secrets.json"


def _read_secrets(path: Path) -> Dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_secrets(path: Path, data: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".secrets-", dir=str(path.parent))
    try:
        os.chmod(tmp, 0o600)  # owner only (on Windows the per-user folder's permissions apply)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def check_key(key: Any) -> str:
    if not isinstance(key, str):
        raise SettingsError("the key must be text")
    key = key.strip()
    if not 20 <= len(key) <= 400 or any(c.isspace() or not c.isprintable() or ord(c) > 126 for c in key):
        raise SettingsError("that does not look like a Claude API key (copy it again from console.anthropic.com)")
    return key


class AssistantSettings:
    def __init__(self, store: Any, initial: Optional[Dict[str, Any]], secrets_path: Optional[Path] = None):
        self.store = store
        self.secrets_path = Path(secrets_path) if secrets_path else default_secrets_path()
        spec = dict(initial or {})
        self.custom_backend = bool(spec.get("backend"))  # a scripted or third-party backend: not configurable here
        self.enabled = bool(initial)
        self.model = str(spec.get("model", MODELS[0]))
        self.effort = str(spec.get("effort", "medium"))
        self.max_tokens = int(spec.get("max_tokens", 16000))
        saved = store.get_meta(META_KEY)
        if saved and not self.custom_backend:
            self.enabled = bool(saved.get("enabled", self.enabled))
            self.model = saved.get("model", self.model)
            self.effort = saved.get("effort", self.effort)
        stored_key = _read_secrets(self.secrets_path).get(SECRET_NAME)
        self.api_key: Optional[str] = stored_key or None
        self.remembered = bool(stored_key)

    # -- what the Configuration tab shows (never the key itself) ---------------------------------------------
    def key_source(self) -> str:
        if self.api_key:
            return "remembered on this computer" if self.remembered else "entered in the Console (until restart)"
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "the ANTHROPIC_API_KEY environment variable"
        if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return "the ANTHROPIC_AUTH_TOKEN environment variable"
        return "none entered: an `ant auth login` sign-in is used if this computer has one"

    def view(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "model": self.model, "effort": self.effort, "models": list(MODELS),
                "efforts": list(EFFORTS), "custom_backend": self.custom_backend,
                "key": {"set": bool(self.api_key), "hint": f"…{self.api_key[-4:]}" if self.api_key else None,
                        "remembered": self.remembered, "source": self.key_source()},
                "secrets_file": str(self.secrets_path) if self.remembered else None}

    # -- changes -------------------------------------------------------------------------------------------------
    def update(self, body: Dict[str, Any]) -> None:
        if self.custom_backend:
            raise SettingsError("this server's assistant uses a custom backend set in its config file")
        unknown = set(body) - {"enabled", "model", "effort", "api_key", "remember", "clear_key"}
        if unknown:
            raise SettingsError(f"unknown settings {sorted(unknown)}")
        if "model" in body and body["model"] not in MODELS:
            raise SettingsError(f"model must be one of {list(MODELS)}")
        if "effort" in body and body["effort"] not in EFFORTS:
            raise SettingsError(f"effort must be one of {list(EFFORTS)}")
        if "enabled" in body and not isinstance(body["enabled"], bool):
            raise SettingsError("enabled must be true or false")
        new_key = check_key(body["api_key"]) if body.get("api_key") else None
        remember = body.get("remember", self.remembered)
        if not isinstance(remember, bool):
            raise SettingsError("remember must be true or false")
        # all checks passed: apply
        self.enabled = body.get("enabled", self.enabled)
        self.model = body.get("model", self.model)
        self.effort = body.get("effort", self.effort)
        if body.get("clear_key"):
            self.api_key = None
        if new_key:
            self.api_key = new_key
        secrets = _read_secrets(self.secrets_path)
        if self.api_key and remember:
            if secrets.get(SECRET_NAME) != self.api_key:
                _write_secrets(self.secrets_path, {**secrets, SECRET_NAME: self.api_key})
            self.remembered = True
        else:
            if SECRET_NAME in secrets:
                secrets.pop(SECRET_NAME)
                _write_secrets(self.secrets_path, secrets)
            self.remembered = False
        self.store.set_meta(META_KEY, {"enabled": self.enabled, "model": self.model, "effort": self.effort})

    def client_factory(self) -> Callable[[], Any]:
        """Build the Claude client: the key entered here, or the SDK's own credential lookup."""
        key = self.api_key

        def make() -> Any:
            import anthropic

            return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()

        return make
