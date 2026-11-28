"""Test package. The whole suite runs with an audit key, as a production server must (see autology.audit)."""

import os

os.environ.setdefault("AUTOLOGY_AUDIT_KEY", "test-suite-audit-key")

# never read or write the developer's real per-user secrets file (the Console's saved Claude key) from tests
import atexit  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

# Everything the suite creates goes under one folder that is removed when the test process ends (GAP-088: each
# test left its temporary folder behind, about 13 MB at a time; a long session filled its disk with 77,000 of them).
# Processes the tests start inherit it through TMPDIR.
_TEMPORARY = tempfile.mkdtemp(prefix="autology-tests-")
tempfile.tempdir = _TEMPORARY
os.environ["TMPDIR"] = _TEMPORARY
atexit.register(shutil.rmtree, _TEMPORARY, ignore_errors=True)

os.environ["AUTOLOGY_SECRETS_FILE"] = os.path.join(tempfile.mkdtemp(prefix="autology-test-"), "secrets.json")
