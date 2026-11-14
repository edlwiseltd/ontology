"""Start the example platform for Studio's browser tests, with its data in a temporary folder (synthetic data)."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
TOKENS = {"ACME_TOKEN_ADA": "acme-ada", "ACME_TOKEN_HANA": "acme-hana", "ACME_TOKEN_IVAN": "acme-ivan",
          "ACME_TOKEN_MARIA": "acme-maria", "ACME_TOKEN_OLIVIA": "acme-olivia", "ACME_TOKEN_LENA": "acme-lena",
          "NORTHWIND_TOKEN_NADIA": "nw-nadia", "NORTHWIND_TOKEN_HANA": "nw-hana"}
os.environ.update(TOKENS)
os.environ.setdefault("AUTOLOGY_AUDIT_KEY", "studio-e2e-key")
ex = ROOT / "examples" / "platform"
spec = json.loads((ex / "platform.json").read_text())
spec["data_dir"] = tempfile.mkdtemp(prefix="studio-e2e-")
for ws in spec["workspaces"].values():
    for uc in ws["use_cases"].values():
        uc["config"] = str((ex / uc["config"]).resolve())
for t in spec.get("templates", {}).values():
    t["config"] = str((ex / t["config"]).resolve())
path = Path(spec["data_dir"]) / "platform.json"
path.write_text(json.dumps(spec))
from autology.platform import serve  # noqa: E402

serve(str(path), "127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8701)
