"""Test package. The whole suite runs with an audit key, as a production server must (see autology.audit)."""

import os

os.environ.setdefault("AUTOLOGY_AUDIT_KEY", "test-suite-audit-key")
