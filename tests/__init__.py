"""Test package. The whole suite runs with an audit key, as a production server must (see autology.audit)."""

import os

os.environ.setdefault("AUTOLOGY_AUDIT_KEY", "test-suite-audit-key")

# never read or write the developer's real per-user secrets file (the Console's saved Claude key) from tests
import tempfile  # noqa: E402

os.environ["AUTOLOGY_SECRETS_FILE"] = os.path.join(tempfile.mkdtemp(prefix="autology-test-"), "secrets.json")
