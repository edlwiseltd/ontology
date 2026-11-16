"""Write the deployment files of a dedicated evaluation platform for one authorised AI provider.

The repository configures no provider (``examples/platform`` names only the sandbox test double). A real provider
is reached only from a deployment that carries the owner's authorisation (decisions D7, D10). This script writes
that deployment **outside the repository**, from the values of the owner's decision, so that nothing about it is
typed by hand and nothing about it is committed:

    python deploy/evaluation_setup.py --out /srv/autology-eval --model claude-opus-5-5 \\
        --monthly-usd 25 --per-request-usd 1 --expires 2026-11-30 --decision "D7/D10, owner, 16 Nov 2026"

It writes ``platform.json`` (one workspace, four people, one use case and one Studio template that name the
provider, its exact model and the policy terms; the owner's authorisation block), the use case's configuration
and ``policy.json`` (the workspace policy for one person to propose and another to approve). It reads no key and
writes none: the policy holds the *name* of the environment variable the key must be in. ``--check`` says whether
that variable is set, never what it holds.

Synthetic data only: the use case is declared ``"content": "synthetic"`` and the policy allows no other class.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autology import ai_policy  # noqa: E402
from autology.reasoners import PRICES  # noqa: E402

PEOPLE = ("owner", "reviewer", "operator", "supervisor")


def policy_of(args: argparse.Namespace, prefix: str) -> dict:
    return {"provider": args.provider, "model": args.model, "data_classes": ["synthetic"], "purposes": ["architect"],
            "limits": {"max_input_tokens": args.max_input_tokens, "max_output_tokens": args.max_output_tokens,
                       "concurrency": 1, "timeout_seconds": args.timeout_seconds, "max_attempts": args.max_attempts},
            "budget": {"currency": "USD", "per_request": args.per_request_usd, "per_period": args.monthly_usd,
                       "period": "month"},
            "credential": {"ref": f"env:{prefix}AI_KEY"}, "retention": {"prompts": "none", "usage_days": 90},
            "evaluation": {"status": "not_evaluated", "reference": "planning/AUTOLOGY_AI_PROVIDER_EVALUATION_PROTOCOL.md"},
            "expires": args.expires}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="a directory outside the repository")
    ap.add_argument("--workspace", default="evaluation")
    ap.add_argument("--provider", default="anthropic")
    ap.add_argument("--model", help="the exact model identifier the owner authorised")
    ap.add_argument("--monthly-usd", type=float, help="the owner's monthly ceiling")
    ap.add_argument("--per-request-usd", type=float, default=1.0)
    ap.add_argument("--expires", help="YYYY-MM-DD: the authorisation and the policy end on this date")
    ap.add_argument("--decision", help="the reference of the owner's decision")
    ap.add_argument("--max-input-tokens", type=int, default=20000)
    ap.add_argument("--max-output-tokens", type=int, default=16000)
    ap.add_argument("--timeout-seconds", type=float, default=300)
    ap.add_argument("--max-attempts", type=int, default=1)
    ap.add_argument("--check", action="store_true", help="only say whether the key variable is set (never its value)")
    args = ap.parse_args(argv)

    prefix = args.workspace.upper().replace("-", "_") + "_"
    variable = f"{prefix}AI_KEY"
    if args.check:
        present = bool(os.environ.get(variable))
        print(f"{variable}: {'set' if present else 'NOT set'} in this environment (its value is never read here)")
        return 0 if present else 1
    missing = [name for name in ("out", "model", "monthly_usd", "expires", "decision")
               if getattr(args, name) in (None, "")]
    if missing:
        ap.error("the owner's decision names: " + ", ".join("--" + m.replace("_", "-") for m in missing))
    out = Path(args.out).resolve()
    if ROOT == out or ROOT in out.parents:
        ap.error("--out must be outside the repository: a deployment with an authorisation is never committed")
    if args.model not in PRICES:
        ap.error(f"no price is registered for {args.model!r}: its cost could not be bounded (autology/reasoners.py)")

    problems, policy = ai_policy.validate_policy(policy_of(args, prefix), prefix)
    if problems:
        ap.error("; ".join(problems))
    authorisation = {"workspace": args.workspace, "provider": args.provider, "model": args.model,
                     "data_classes": ["synthetic"], "max_budget_usd_per_month": args.monthly_usd,
                     "expires": args.expires, "decision": args.decision}
    ai_policy.validate_authorisations([authorisation], {args.workspace})
    covered, reason = ai_policy.authorisation_for(policy, args.workspace, [authorisation])
    if covered is None:
        ap.error(f"the authorisation would not cover the policy: {reason}")

    terms = ai_policy.terms_fingerprint(policy)
    setting = {"provider": args.provider, "model": args.model, "policy": terms, "data_classes": ["synthetic"],
               "content": "synthetic"}
    usecase = out / "usecase"
    usecase.mkdir(parents=True, exist_ok=True)
    blank = json.loads((ROOT / "examples" / "onboarding" / "server.json").read_text())
    shutil.copyfile(ROOT / "examples" / "onboarding" / "ontology.json", usecase / "ontology.json")
    (usecase / "server.json").write_text(json.dumps({**blank, "ai": setting}, indent=2) + "\n")
    platform = {
        "data_dir": "data",
        "templates": {"claude-solution": {
            "name": f"Blank solution with the authorised architect ({args.model})",
            "description": "An empty model; the architect is the authorised language model. Synthetic descriptions "
                           "only: never a real customer, person or contract",
            "config": "usecase/server.json"}},
        "workspaces": {args.workspace: {
            "name": "Architect evaluation (synthetic data only)",
            "release_approvers": ["reviewer"],
            "members": [{"name": "owner", "token_env": f"{prefix}TOKEN_OWNER", "workspace_admin": True}]
            + [{"name": name, "token_env": f"{prefix}TOKEN_{name.upper()}"} for name in PEOPLE[1:]],
            "use_cases": {"architect": {"name": "Architect evaluation", "config": "usecase/server.json"}}}},
        "ai_authorisations": [authorisation]}
    (out / "platform.json").write_text(json.dumps(platform, indent=2) + "\n")
    (out / "policy.json").write_text(json.dumps({"policy": policy_of(args, prefix),
                                                 "reason": f"architect evaluation ({args.decision})"}, indent=2) + "\n")
    (out / "WRITTEN").write_text(datetime.now(timezone.utc).isoformat() + "\n")

    print(f"Written to {out}: platform.json, policy.json, usecase/")
    print(f"  workspace {args.workspace}; provider {args.provider}; model {args.model}; synthetic data only")
    print(f"  ceiling {args.monthly_usd:g} USD a month, {args.per_request_usd:g} USD a request, one call at a time; "
          f"until {args.expires}")
    print(f"  policy terms {terms} (named by the use case and by every release of it)")
    print(f"  the key is read from the environment variable {variable} "
          f"({'set' if os.environ.get(variable) else 'NOT set'} here); it is written nowhere")
    print("Next: set an audit key and one token per person, start the platform, then one person proposes "
          "policy.json and another approves it:")
    print("  export AUTOLOGY_AUDIT_KEY=... " + " ".join(f"{prefix}TOKEN_{p.upper()}=..." for p in PEOPLE))
    print(f"  python -m autology platform {out / 'platform.json'} --port 8700")
    print(f"  POST /platform/workspaces/{args.workspace}/ai/policy            (owner, body: policy.json)")
    print(f"  POST /platform/workspaces/{args.workspace}/ai/policy/<id>/approve  (reviewer)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
