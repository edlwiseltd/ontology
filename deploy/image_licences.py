"""Check the licences of what a built Docker image really contains (GAP-031). Standard library only.

    docker run --rm -i --entrypoint python IMAGE - < deploy/image_licences.py > installed.json   # list (in the image)
    python deploy/image_licences.py check installed.json [--no-weak-copyleft]                  # check (on the host)

``check`` fails when a package in the image is missing from ``deploy/third_party_licences.json``, when its family
is forbidden by the inventory's policy, when its version differs from ``deploy/image-constraints.txt``, or (with
``--no-weak-copyleft``) when the image contains any weak-copyleft component. It prints the components that need the
legal review. It reports facts for counsel; it draws no legal conclusion.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"autology", "pip"}


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def installed():
    from importlib import metadata

    out = []
    for dist in metadata.distributions():
        md = dist.metadata
        out.append({"name": norm(md["Name"]), "version": md["Version"],
                    "licence": (md.get("License-Expression") or md.get("License") or "").split("\n")[0][:80]})
    return sorted(out, key=lambda d: d["name"])


def check(path, no_weak_copyleft=False):
    inventory = json.loads((ROOT / "deploy" / "third_party_licences.json").read_text())
    packages = dict(inventory["packages"]) if isinstance(inventory["packages"], list) else inventory["packages"]
    packages = {norm(k): v for k, v in packages.items()}
    policy = inventory["_policy"]
    pins = {norm(line.split("==")[0]): line.split("==")[1].strip()
            for line in (ROOT / "deploy" / "image-constraints.txt").read_text().splitlines()
            if "==" in line and not line.startswith("#")}
    problems, review = [], []
    for item in json.loads(Path(path).read_text()):
        name = item["name"]
        if name in SKIP:
            continue
        meta = packages.get(name)
        if meta is None:
            problems.append(f"{name} {item['version']} is in the image but not in deploy/third_party_licences.json")
            continue
        if meta["family"] in policy["forbidden"]:
            problems.append(f"{name}: {meta['licence']} is forbidden by the licence policy")
        if meta["family"] in policy["needs_legal_review"]:
            review.append(f"{name} {item['version']} ({meta['licence']})")
            if no_weak_copyleft:
                problems.append(f"{name} ({meta['licence']}) must not be in this image")
        if pins.get(name) != item["version"]:
            problems.append(f"{name} {item['version']} differs from deploy/image-constraints.txt ({pins.get(name)})")
    print("needs the legal review:", ", ".join(review) or "none")
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "check":
        sys.exit(check(sys.argv[2], "--no-weak-copyleft" in sys.argv))
    print(json.dumps(installed(), indent=1))
