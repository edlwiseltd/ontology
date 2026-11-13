"""Shared PoC harness: in-process AutologyService built on examples/order_fulfilment."""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("AUTOLOGY_AUDIT_KEY", "poc-audit-key")
ROOT = Path("/home/user/ontology")
sys.path.insert(0, str(ROOT))
from autology.server import AutologyService, ApiError, hash_token, make_server  # noqa: E402

EX = ROOT / "examples" / "order_fulfilment"
TOKENS = {"olivia": "tok-olivia", "lena": "tok-lena", "audrey": "tok-audrey", "admin": "tok-admin",
          "rita": "tok-rita", "ivan": "tok-ivan", "rory": "tok-rory"}


def service(extra_users=(), **overrides):
    for name, token in TOKENS.items():
        os.environ[f"AUTOLOGY_TOKEN_{name.upper()}"] = token
    cfg = json.loads((EX / "server.json").read_text())
    cfg["store"] = str(Path(tempfile.mkdtemp()) / "api.db")
    cfg.pop("chat", None)
    cfg["users"] = cfg["users"] + list(extra_users)
    cfg.update(overrides)
    return AutologyService(cfg, EX)


def user(svc, name):
    return next(u for u in svc.users if u.name == name)


def add_big_order(svc, region="US"):
    admin = user(svc, "admin")
    svc.upsert_object(admin, {"type": "Order", "id": "O-4", "attributes": {
        "sku": "TURBINE-1", "quantity": 1, "amount": 85000, "region": region, "hazardous": False}})
    svc.upsert_object(admin, {"type": "Contract", "id": "K-2", "attributes": {"value": 120000},
                              "links": [{"kind": "covers", "target": "O-4"}]})
    svc.upsert_object(admin, {"type": "Customer", "id": "C-2", "attributes": {
        "name": "Contoso Power", "region": "US", "credit_limit": 500000, "status": "approved"},
        "links": [{"kind": "hasContract", "target": "K-2"}]})


def call(svc_fn, *a, **kw):
    try:
        return 200, svc_fn(*a, **kw)
    except ApiError as e:
        return e.status, {"error": e.message, **e.extra}


class Api:
    def __init__(self, service):
        self.server = make_server(service, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def call(self, method, path, who=None, body=None, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        hdrs = {"Content-Type": "application/json", **(headers or {})}
        if who:
            hdrs["Authorization"] = f"Bearer {TOKENS.get(who, who)}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                payload = r.read()
                try:
                    return r.status, json.loads(payload)
                except ValueError:
                    return r.status, payload.decode()
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                return e.code, json.loads(body)
            except ValueError:
                return e.code, body.decode(errors="replace")
