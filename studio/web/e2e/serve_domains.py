"""Start the two-application platform of examples/domains for Studio's cross-domain browser tests (synthetic data)."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
ex = ROOT / "examples" / "domains"
spec = json.loads((ex / "platform.json").read_text())
for ws, body in spec["workspaces"].items():
    for member in body["members"]:
        os.environ[member["token_env"]] = f"{ws}-{member['name']}"
os.environ.setdefault("AUTOLOGY_AUDIT_KEY", "studio-e2e-key")
spec["data_dir"] = tempfile.mkdtemp(prefix="studio-e2e-domains-")
for t in spec["templates"].values():
    t["config"] = str((ex / t["config"]).resolve())
path = Path(spec["data_dir"]) / "platform.json"
path.write_text(json.dumps(spec))
from autology.platform import serve  # noqa: E402

serve(str(path), "127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8702)
