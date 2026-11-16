"""AI provider governance per workspace: the policy, the owner's authorisation, and the spending ledger.

Three things must all be true before a request of a workspace may leave for a provider (design:
planning/AUTOLOGY_AI_PROVIDER_WORKSPACE_CONFIGURATION_DESIGN.md):

1. **A workspace policy** exists and was approved by a second person (:func:`validate_policy`). It names the
   provider and model, the data classes that may be sent, the permitted purposes, limits, budgets, where the key
   lives (a reference, never the key) and the retention rule. A policy is configuration: stored in the workspace's
   signed administration log, it is **not** by itself permission to transmit anything.
2. **The owner's authorisation** covers it (:func:`authorisation_for`). It is part of the platform's deployment
   configuration (``"ai_authorisations"``), written by the operator from an owner decision (D7, D10): it cannot be
   created through the API, and no authorisation exists unless someone deploys one. The sandbox test double needs
   none: it contacts nothing.
3. **The budget allows it** (:class:`SpendLedger`): a durable, append-style ledger per workspace. Money is
   reserved before a call, in the same transaction that checks the ceilings and the concurrency limit, and
   settled to what was actually used afterwards. If the ledger cannot be read or written the call is refused.

Nothing here contacts a provider. The gateway (:mod:`autology.ai`) asks :class:`Budget` before each call.
"""

from __future__ import annotations

import math
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .ai import DATA_CLASSES, ModelRequest, ProviderError
from .reasoners import PRICES, estimate_cost, is_priced

PURPOSES = ("architect",)  # what a model may be used for today; nothing else reaches the gateway through a policy
PERIODS = ("day", "month")
NO_AUTHORISATION_NEEDED = ("sandbox",)  # deterministic test doubles: they contact nothing
ENV_REF = re.compile(r"^env:([A-Z][A-Z0-9_]{2,63})$")
NAME = re.compile(r"^[a-z0-9][a-z0-9._\-]{0,63}$")
CHARS_PER_TOKEN = 3  # a deliberately low figure: the estimate before a call errs on the expensive side


def _number(value: Any, low: float, high: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high


def _part(spec: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = spec.get(key)
    return value if isinstance(value, Mapping) else {}


def validate_policy(spec: Any, env_prefix: str = "") -> Tuple[List[str], Dict[str, Any]]:
    """``(problems, policy)``: what is wrong with a proposed policy, and its normal form when nothing is."""
    problems: List[str] = []
    if not isinstance(spec, Mapping):
        return ["a policy is an object"], {}
    known = {"provider", "model", "data_classes", "purposes", "limits", "budget", "credential", "retention",
             "evaluation", "expires"}
    extra = sorted(set(spec) - known)
    if extra:
        problems.append(f"unknown keys {extra}")
    provider, model = spec.get("provider"), spec.get("model")
    if not isinstance(provider, str) or not NAME.match(provider):
        problems.append("provider: a provider identifier")
    if not isinstance(model, str) or not 1 <= len(model) <= 120:
        problems.append("model: the exact model identifier")
    classes: Any = spec.get("data_classes")
    if not isinstance(classes, list) or not classes or set(classes) - set(DATA_CLASSES):
        problems.append(f"data_classes: a non-empty list taken from {list(DATA_CLASSES)}")
    purposes: Any = spec.get("purposes")
    if not isinstance(purposes, list) or not purposes or set(purposes) - set(PURPOSES):
        problems.append(f"purposes: a non-empty list taken from {list(PURPOSES)}")
    limits = _part(spec, "limits")
    wanted = {"max_input_tokens": (1, 2_000_000), "max_output_tokens": (1, 200_000), "concurrency": (1, 64),
              "timeout_seconds": (1, 600), "max_attempts": (1, 5)}
    for key, (low, high) in wanted.items():
        if not _number(limits.get(key), low, high):
            problems.append(f"limits.{key}: a number from {low} to {high}")
    if set(limits) - set(wanted):
        problems.append(f"limits: unknown keys {sorted(set(limits) - set(wanted))}")
    budget = _part(spec, "budget")
    if budget.get("currency") != "USD":
        problems.append("budget.currency: USD (the only currency the price table knows)")
    if not _number(budget.get("per_request"), 0, 1_000_000) or not _number(budget.get("per_period"), 0, 10_000_000):
        problems.append("budget.per_request and budget.per_period: amounts, zero or more")
    if budget.get("period") not in PERIODS:
        problems.append(f"budget.period: one of {list(PERIODS)}")
    if set(budget) - {"currency", "per_request", "per_period", "period"}:
        problems.append("budget: unknown keys")
    credential = spec.get("credential")
    if provider in NO_AUTHORISATION_NEEDED:
        if credential not in (None, {}):
            problems.append("credential: the sandbox holds no credential")
        reference = None
    else:
        reference = credential.get("ref") if isinstance(credential, Mapping) else None
        match = ENV_REF.match(reference) if isinstance(reference, str) else None
        if match is None or (isinstance(credential, Mapping) and set(credential) - {"ref"}):
            # never echo what was sent: it may be a key pasted where a reference belongs
            problems.append("credential: {\"ref\": \"env:NAME\"}, a reference to where the key lives, never the key")
        elif env_prefix and not match.group(1).startswith(env_prefix):
            problems.append(f"credential.ref: an environment variable under this workspace's prefix {env_prefix!r}")
    retention = _part(spec, "retention")
    if retention.get("prompts") != "none" or not _number(retention.get("usage_days"), 1, 3650) \
            or set(retention) - {"prompts", "usage_days"}:
        problems.append("retention: {\"prompts\": \"none\", \"usage_days\": 1..3650} (prompts and answers are not "
                        "kept by the gateway; whether a provider may retain them is an owner decision)")
    evaluation = _part(spec, "evaluation")
    if evaluation.get("status") not in ("not_evaluated", "evaluated") or set(evaluation) - {"status", "reference"}:
        problems.append("evaluation: {\"status\": \"not_evaluated\" | \"evaluated\", \"reference\": ...}")
    expires = spec.get("expires")
    if expires is not None and _parse_date(expires) is None:
        problems.append("expires: a date such as 2027-01-31, or nothing")
    if problems:
        return problems, {}
    return [], {"provider": provider, "model": model, "data_classes": sorted(set(classes)),
                "purposes": sorted(set(purposes)),
                "limits": {k: (float(limits[k]) if k == "timeout_seconds" else int(limits[k])) for k in wanted},
                "budget": {"currency": "USD", "per_request": float(budget["per_request"]),
                           "per_period": float(budget["per_period"]), "period": budget["period"]},
                "credential": {"ref": reference} if reference else None,
                "retention": {"prompts": "none", "usage_days": int(retention["usage_days"])},
                "evaluation": {"status": evaluation["status"], "reference": str(evaluation.get("reference") or "")[:200]},
                "expires": expires}


def _parse_date(value: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def validate_authorisations(spec: Any, workspaces: Any) -> List[Dict[str, Any]]:
    """The owner's authorisations from the platform's deployment configuration, checked. Raises ``ValueError``."""
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(spec or []):
        where = f"ai_authorisations[{i}]"
        if not isinstance(item, Mapping) or set(item) - {"workspace", "provider", "model", "data_classes",
                                                         "max_budget_usd_per_month", "expires", "decision"}:
            raise ValueError(f"{where}: workspace, provider, model, data_classes, max_budget_usd_per_month, expires, "
                             "decision")
        if item.get("workspace") not in workspaces:
            raise ValueError(f"{where}: unknown workspace {item.get('workspace')!r}")
        if not isinstance(item.get("decision"), str) or not item["decision"].strip():
            raise ValueError(f"{where}: decision: the reference of the owner's decision that authorises it")
        if not isinstance(item.get("data_classes"), list) or set(item["data_classes"]) - set(DATA_CLASSES):
            raise ValueError(f"{where}: data_classes taken from {list(DATA_CLASSES)}")
        if not _number(item.get("max_budget_usd_per_month"), 0, 10_000_000):
            raise ValueError(f"{where}: max_budget_usd_per_month: an amount")
        if _parse_date(item.get("expires")) is None:
            raise ValueError(f"{where}: expires: a date such as 2027-01-31 (an authorisation is never open-ended)")
        if not isinstance(item.get("provider"), str) or not isinstance(item.get("model"), str):
            raise ValueError(f"{where}: provider and model")
        out.append(dict(item))
    return out


def authorisation_for(policy: Mapping[str, Any], workspace: str, authorisations: Sequence[Mapping[str, Any]],
                      now: Optional[datetime] = None) -> Tuple[Optional[Mapping[str, Any]], str]:
    """``(authorisation, reason)``: the owner's authorisation that covers ``policy`` for ``workspace``, or None and
    why none does. The sandbox needs none."""
    if policy["provider"] in NO_AUTHORISATION_NEEDED:
        return {"decision": "none needed: a test double that contacts nothing"}, ""
    now = now or datetime.now(timezone.utc)
    mine = [a for a in authorisations if a["workspace"] == workspace and a["provider"] == policy["provider"]]
    if not mine:
        return None, (f"the owner has not authorised {policy['provider']} for this workspace (decisions D7 and D10): "
                      "a policy is configuration, not permission to transmit")
    reasons = []
    for a in mine:
        expires = _parse_date(a["expires"])
        monthly = policy["budget"]["per_period"] * (31 if policy["budget"]["period"] == "day" else 1)
        if a["model"] != policy["model"]:
            reasons.append(f"the authorisation names the model {a['model']}, not {policy['model']}")
        elif set(policy["data_classes"]) - set(a["data_classes"]):
            reasons.append(f"the authorisation does not cover {sorted(set(policy['data_classes']) - set(a['data_classes']))}")
        elif expires is None or now >= expires:
            reasons.append(f"the authorisation expired on {a['expires']}")
        elif monthly > a["max_budget_usd_per_month"]:
            reasons.append(f"the policy could spend {monthly:g} USD a month; the authorisation allows "
                           f"{a['max_budget_usd_per_month']:g}")
        else:
            return a, ""
    return None, "; ".join(reasons)


def period_key(period: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d" if period == "day" else "%Y-%m")


SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT, workspace TEXT NOT NULL, use_case TEXT NOT NULL, request_id TEXT NOT NULL,
    purpose TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, period TEXT NOT NULL, state TEXT NOT NULL,
    reserved_usd REAL NOT NULL, actual_usd REAL NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, outcome TEXT NOT NULL DEFAULT '',
    reserved_at TEXT NOT NULL, closed_at TEXT, UNIQUE (workspace, request_id));
CREATE TABLE IF NOT EXISTS ai_refusals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, workspace TEXT NOT NULL, use_case TEXT NOT NULL, request_id TEXT NOT NULL,
    purpose TEXT NOT NULL, reason TEXT NOT NULL, at TEXT NOT NULL);
"""
OPEN, SETTLED, RELEASED, UNCERTAIN = "reserved", "settled", "released", "uncertain"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SpendLedger:
    """What each workspace reserved and spent on model calls. One SQLite file for the platform; every check and
    its reservation are one transaction, so parallel calls cannot spend the same money twice. It holds amounts,
    token counts and outcomes: never a prompt, an answer or a key."""

    def __init__(self, path: Any):
        self.path = str(path)
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def reserve(self, workspace: str, use_case: str, request: ModelRequest, policy: Mapping[str, Any],
                amount: float, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> Dict[str, Any]:
        """Reserve ``amount`` for one request, or raise :class:`ProviderError` (``budget_exceeded``). A request id
        seen before is not reserved again: its row is returned (``duplicate``), so a retry or a repeated click
        never doubles a charge."""
        period = period_key(policy["budget"]["period"], clock())
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute("SELECT * FROM ai_ledger WHERE workspace=? AND request_id=?",
                                       (workspace, request.request_id)).fetchone()
                if row is not None:
                    self._db.execute("COMMIT")
                    return {**dict(row), "duplicate": True}
                committed = self._db.execute(
                    "SELECT COALESCE(SUM(CASE WHEN state=? THEN actual_usd WHEN state IN (?, ?) THEN reserved_usd "
                    "ELSE 0 END), 0) FROM ai_ledger WHERE workspace=? AND period=?",
                    (SETTLED, OPEN, UNCERTAIN, workspace, period)).fetchone()[0]
                running = self._db.execute("SELECT COUNT(*) FROM ai_ledger WHERE workspace=? AND state=?",
                                           (workspace, OPEN)).fetchone()[0]
                refusal = None
                if amount > policy["budget"]["per_request"]:
                    refusal = (f"this request could cost {amount:.4f} USD; the workspace allows "
                               f"{policy['budget']['per_request']:g} per request")
                elif committed + amount > policy["budget"]["per_period"]:
                    refusal = (f"the workspace's AI budget for this {policy['budget']['period']} is "
                               f"{policy['budget']['per_period']:g} USD; {committed:.4f} is spent or reserved and this "
                               f"request could cost {amount:.4f}")
                elif running >= policy["limits"]["concurrency"]:
                    refusal = (f"{running} model requests of this workspace are in progress; its limit is "
                               f"{policy['limits']['concurrency']}")
                if refusal:
                    self._db.execute("INSERT INTO ai_refusals (workspace, use_case, request_id, purpose, reason, at) "
                                     "VALUES (?, ?, ?, ?, ?, ?)",
                                     (workspace, use_case, request.request_id, request.purpose, refusal, _now()))
                    self._db.execute("COMMIT")
                    raise ProviderError("budget_exceeded", refusal)
                cursor = self._db.execute(
                    "INSERT INTO ai_ledger (workspace, use_case, request_id, purpose, provider, model, period, state, "
                    "reserved_usd, reserved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (workspace, use_case, request.request_id, request.purpose, policy["provider"], policy["model"],
                     period, OPEN, float(amount), _now()))
                self._db.execute("COMMIT")
                return {"id": cursor.lastrowid, "duplicate": False, "state": OPEN, "reserved_usd": float(amount)}
            except ProviderError:
                raise
            except BaseException:
                try:
                    self._db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    def close_entry(self, entry: int, state: str, actual: float, usage: Mapping[str, int], attempts: int,
                    outcome: str) -> None:
        """Settle (what was used), release (nothing was sent or billed) or mark uncertain (the provider may have
        processed the call: the reservation stays charged until someone reconciles it)."""
        with self._lock:
            self._db.execute(
                "UPDATE ai_ledger SET state=?, actual_usd=?, input_tokens=?, output_tokens=?, attempts=?, outcome=?, "
                "closed_at=? WHERE id=? AND state=?",
                (state, float(actual), int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)),
                 int(attempts), outcome, _now(), entry, OPEN))

    def usage(self, workspace: str, period: str, now: Optional[datetime] = None) -> Dict[str, Any]:
        key = period_key(period, now)
        with self._lock:
            rows = [dict(r) for r in self._db.execute(
                "SELECT state, COUNT(*) AS n, COALESCE(SUM(reserved_usd), 0) AS reserved, COALESCE(SUM(actual_usd), 0) "
                "AS actual, COALESCE(SUM(input_tokens), 0) AS tin, COALESCE(SUM(output_tokens), 0) AS tout "
                "FROM ai_ledger WHERE workspace=? AND period=? GROUP BY state", (workspace, key))]
            refused = self._db.execute("SELECT COUNT(*) FROM ai_refusals WHERE workspace=? AND at LIKE ?",
                                       (workspace, key + "%")).fetchone()[0]
            recent = [dict(r) for r in self._db.execute(
                "SELECT use_case, purpose, reason, at FROM ai_refusals WHERE workspace=? ORDER BY id DESC LIMIT 5",
                (workspace,))]
        by = {r["state"]: r for r in rows}
        spent = float(by.get(SETTLED, {}).get("actual", 0))
        held = float(by.get(OPEN, {}).get("reserved", 0)) + float(by.get(UNCERTAIN, {}).get("reserved", 0))
        return {"period": key, "spent_usd": round(spent, 6), "reserved_usd": round(held, 6),
                "requests": sum(r["n"] for r in rows), "settled": by.get(SETTLED, {}).get("n", 0),
                "in_progress": by.get(OPEN, {}).get("n", 0), "uncertain": by.get(UNCERTAIN, {}).get("n", 0),
                "released": by.get(RELEASED, {}).get("n", 0), "refused": refused,
                "input_tokens": sum(r["tin"] for r in rows), "output_tokens": sum(r["tout"] for r in rows),
                "recent_refusals": recent}

    def entries(self, workspace: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM ai_ledger WHERE workspace=? ORDER BY id",
                                                      (workspace,))]


def estimate(request: ModelRequest, policy: Mapping[str, Any]) -> Tuple[int, float]:
    """``(input tokens, USD)``: what one request could cost at most, computed before it is sent, from its size
    and the registered price. Never from anything a model says."""
    tokens_in = math.ceil((len(request.system) + len(request.text())) / CHARS_PER_TOKEN)
    tokens_out = min(int(request.max_output_tokens), policy["limits"]["max_output_tokens"])
    once = estimate_cost(policy["model"], {"input_tokens": tokens_in, "output_tokens": tokens_out})
    return tokens_in, once * policy["limits"]["max_attempts"]


class Budget:
    """What the gateway asks before and after each call of one use case (see :meth:`ModelGateway.invoke`)."""

    def __init__(self, ledger: SpendLedger, workspace: str, use_case: str, policy: Mapping[str, Any]):
        self.ledger, self.workspace, self.use_case, self.policy = ledger, workspace, use_case, dict(policy)

    def admit(self, request: ModelRequest) -> int:
        """The ledger entry reserved for ``request``.
        Raises :class:`ProviderError` when the policy or the budget refuses it. Any failure to read or write the
        ledger refuses the request (fail closed)."""
        policy = self.policy
        if request.purpose.split(".")[0] not in policy["purposes"]:
            raise ProviderError("not_allowed", f"this workspace's AI policy does not permit the purpose "
                                               f"{request.purpose!r} (permitted: {policy['purposes']})")
        if policy["provider"] not in NO_AUTHORISATION_NEEDED and not is_priced(policy["model"]):
            raise ProviderError("not_allowed", f"no price is registered for the model {policy['model']}: its cost "
                                               "could not be bounded, so it is not called")
        tokens_in, amount = estimate(request, policy)
        if tokens_in > policy["limits"]["max_input_tokens"]:
            raise ProviderError("not_allowed", f"the request is about {tokens_in} input tokens; the workspace allows "
                                               f"{policy['limits']['max_input_tokens']}")
        try:
            entry = self.ledger.reserve(self.workspace, self.use_case, request, policy, amount)
        except ProviderError:
            raise
        except Exception as exc:  # the ledger is unavailable: nothing is sent
            raise ProviderError("budget_exceeded", f"the spending ledger is unavailable ({type(exc).__name__}): no "
                                                   "request is sent without it") from None
        if entry["duplicate"]:  # accounted for once already, and its answer is no longer held: never sent twice
            raise ProviderError("invalid_request", "this request id was already used; a repeated request is "
                                                   "answered from the first one or refused, never charged twice")
        return int(entry["id"])

    def settle(self, entry: Optional[int], *, usage: Mapping[str, int], cost: float, attempts: int, outcome: str,
               uncertain: bool) -> None:
        if entry is None:
            return
        if uncertain:  # the provider may have done the work: keep the reservation charged
            self.ledger.close_entry(entry, UNCERTAIN, 0.0, usage, attempts, outcome)
        elif attempts == 0 or (outcome != "ok" and not usage):
            self.ledger.close_entry(entry, RELEASED, 0.0, usage, attempts, outcome)
        else:
            self.ledger.close_entry(entry, SETTLED, cost, usage, attempts, outcome)


def describe(policy: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """A policy as it may be shown: everything but where the key lives is repeated; the reference is named, and
    no key was ever part of it."""
    if policy is None:
        return None
    out = {k: v for k, v in policy.items() if k != "credential"}
    out["credential"] = {"ref": policy["credential"]["ref"], "note": "a reference; the key is never stored or shown"} \
        if policy.get("credential") else None
    out["priced"] = policy["provider"] in NO_AUTHORISATION_NEEDED or policy["model"] in PRICES
    return out


