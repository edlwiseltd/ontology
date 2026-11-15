"""Type-checking ratchet (QA-1, audit GAP-025 / F-12): the number of mypy errors may only go down.

    python deploy/mypy_ratchet.py            # fails if autology/ has more errors than deploy/mypy-baseline.txt
    python deploy/mypy_ratchet.py --update   # after fixing errors: lower the baseline to the new count

The baseline was measured on 15 November 2026 (mypy 2.4.1). Fixing errors and lowering the baseline is welcome;
raising it needs a written reason in the commit.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "deploy" / "mypy-baseline.txt"


def count() -> int:
    out = subprocess.run([sys.executable, "-m", "mypy", "--ignore-missing-imports", "--no-error-summary", "autology"],
                         cwd=ROOT, capture_output=True, text=True)
    if out.returncode not in (0, 1):  # 2: mypy itself failed (bad config, crash): never pass silently
        sys.exit(f"mypy did not run: {out.stderr or out.stdout}")
    errors = [line for line in out.stdout.splitlines() if ": error:" in line]
    return len(errors)


def main() -> int:
    now = count()
    allowed = int(BASELINE.read_text().split()[0])
    if "--update" in sys.argv:
        if now > allowed:
            sys.exit(f"{now} errors is more than the baseline {allowed}: fix them instead of raising the baseline")
        BASELINE.write_text(f"{now}\n")
        print(f"baseline set to {now}")
        return 0
    if now > allowed:
        print(f"FAIL: {now} mypy errors, the baseline allows {allowed}: fix the new ones (run mypy autology)")
        return 1
    print(f"OK: {now} mypy errors (baseline {allowed})" + ("; lower it with --update" if now < allowed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
