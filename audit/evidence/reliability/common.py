"""Shared helpers for the reliability audit scenarios (local only)."""
import copy
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path("/home/user/ontology")
sys.path.insert(0, str(ROOT))
EX = ROOT / "examples" / "auto_insurance"
TOKENS = {"hana": "tok-hana", "ivan": "tok-ivan", "maria": "tok-maria", "etl": "tok-etl", "admin": "tok-admin-ai"}
for _n, _t in TOKENS.items():
    os.environ[f"AUTOLOGY_TOKEN_{_n.upper()}"] = _t
os.environ.setdefault("AUTOLOGY_AUDIT_KEY", "k")

SCRATCH = Path(__file__).resolve().parent / "work"
SCRATCH.mkdir(exist_ok=True)


def workdir(name):
    d = Path(tempfile.mkdtemp(prefix=name + "-", dir=SCRATCH))
    return d


def tools_json(path, overrides=None):
    """Write a tools.json copy of the example with tool specs replaced by name (e.g. an http payments tool)."""
    cfg = json.loads((EX / "tools.json").read_text())
    overrides = overrides or {}
    tools = []
    for t in cfg["tools"]:
        tools.append(overrides.pop(t["name"], t) if t["name"] in overrides else t)
    tools.extend(overrides.values())  # new tools
    cfg["tools"] = [t for t in tools if t is not None]
    Path(path).write_text(json.dumps(cfg, indent=1))
    return path


def server_config(d, tools_path=None, ontology_path=None, automations=False, extra=None):
    cfg = json.loads((EX / "server.json").read_text())
    cfg["store"] = str(Path(d) / "claims.db")
    cfg["data"] = str(EX / "data.json")
    cfg["ontology"] = str(ontology_path or (EX / "ontology.json"))
    cfg["agents"]["claims"]["tools"] = str(tools_path or (EX / "tools.json"))
    cfg["pipelines"] = {"claims_feed": str(EX / "pipelines" / "claims_feed.json")}
    if not automations:
        cfg["automations"] = {}
    if extra:
        cfg.update(extra)
    p = Path(d) / "server.json"
    p.write_text(json.dumps(cfg, indent=1))
    return p


def service(cfg_path):
    from autology.server import AutologyService
    cfg = json.loads(Path(cfg_path).read_text())
    return AutologyService(cfg, Path(cfg_path).parent)


def users(svc):
    return {u.name: u for u in svc.users}


class Recorder:
    """A local fake external system. behaviour(call_no, body) -> (status, body_dict_or_str, delay_s, close)."""

    def __init__(self, behaviour, log_path=None):
        self.calls = []
        self.behaviour = behaviour
        self.log_path = log_path
        rec = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                headers = dict(self.headers)
                rec.calls.append({"t": time.time(), "body": body, "headers": headers})
                if rec.log_path:
                    with open(rec.log_path, "a") as f:
                        f.write(json.dumps({"t": time.time(), "body": body}) + "\n")
                status, reply, delay, close = rec.behaviour(len(rec.calls), body)
                if delay:
                    time.sleep(delay)
                if close:
                    self.close_connection = True
                    try:
                        self.connection.shutdown(2)
                    except Exception:
                        pass
                    return
                data = reply if isinstance(reply, (bytes, str)) else json.dumps(reply)
                data = data.encode() if isinstance(data, str) else data
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception:
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/pay"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def show(title, value):
    print(f"  {title}: {value}")


def audit_events(result):
    return [(e.event, {k: v for k, v in e.data.items() if k in ("action", "tool", "attempt", "error", "status",
                                                                  "outcome", "approved", "reason")})
            for e in result.audit]
