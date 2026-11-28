"""A synthetic reference client: how a domain application consumes a released Autology solution.

This is **not Studio** and **not an operational application**. It is a prototype of the contract in
``docs/application-contract.md``, on invented data, with simulated tools. It shows that an application needs nothing
but the Engine's versioned API and an identity of its own: it holds no rules, no workflow and no permissions.

* :class:`Application` is the same for every domain: connect (identity, model, what it may do), read records it is
  allowed to read, ask for a governed action, look at reviews, read the audit trail.
* The functions below it are two small **domain views** built only from those calls: an evidence graph for the
  network-intelligence demonstrator, and the resources around an incident for the crisis demonstrator. They compute
  nothing a person could not read from the records; they forecast nothing, accuse nobody and decide nothing.

    python examples/domains/reference_app.py --url http://127.0.0.1:8700 --workspace netintel --use-case cases \
        --token-env APP_TOKEN evidence-graph

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

CLASSES = ("observed_fact", "confirmed_assertion", "inference", "unresolved_hypothesis")


class ContractError(Exception):
    """The solution the application found is not the one it was built for, or the Engine refused a call."""


class Application:
    """A domain application's connection to one use case of one workspace."""

    def __init__(self, url: str, workspace: str, use_case: str, token: str, expects: Optional[Dict[str, Any]] = None):
        self.base = f"{url.rstrip('/')}/w/{workspace}/u/{use_case}/api/v1"
        self.outline = f"{url.rstrip('/')}/platform/v1/workspaces/{workspace}/use-cases/{use_case}"
        self.token, self.expects = token, dict(expects or {})
        self.refused: List[Dict[str, Any]] = []  # every call the Engine refused, kept for the application's own log

    def call(self, method: str, path: str, body: Any = None) -> Tuple[int, Any]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(path if path.startswith("http") else self.base + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as answer:
                return answer.status, json.loads(answer.read() or b"{}")
        except urllib.error.HTTPError as exc:
            out = json.loads(exc.read() or b"{}")
            self.refused.append({"method": method, "path": path, "status": exc.code,
                                 "message": (out.get("error") or {}).get("message", "")})
            return exc.code, out

    def need(self, method: str, path: str, body: Any = None) -> Any:
        status, out = self.call(method, path, body)
        if status != 200:
            raise ContractError(f"{method} {path}: HTTP {status}: {(out.get('error') or {}).get('message', out)}")
        return out

    # -- the contract ----------------------------------------------------------------------------------
    def connect(self) -> Dict[str, Any]:
        """Who the application is here, which model is released, and what the solution declares. Refuses to go on
        when the solution is not the one the application expects (``expects``: ``model``, ``fingerprint``,
        ``release``, ``stages``, ``case_templates``, ``actions``) or when no release is active."""
        me, model, outline = self.need("GET", "/me"), self.need("GET", "/ontology"), self.need("GET", self.outline)
        active = (outline.get("release") or {}).get("active") or {}
        found = {"identity": me["name"], "kind": me["kind"], "permissions": me["permissions"], "roles": me["roles"],
                 # the release that runs: every run this application asks for names the same fingerprint
                 "release": {"number": active.get("number"), "id": active.get("id"), "fingerprint": active.get("fingerprint")},
                 "stage": outline.get("effective_stage"),
                 "model": model["ref"], "fingerprint": model["fingerprint"],
                 "case_templates": {k: v["root"] for k, v in model["case_templates"].items()},
                 "actions": sorted(model["actions"]), "agents": model["agents"],
                 "entities": {k: v["states"] for k, v in model["entities"].items()},
                 "relationships": model["relationships"], "rules": model["rules"]}
        name = found["model"].split("@")[0]
        problems = []
        if self.expects.get("model") not in (None, name):
            problems.append(f"model {name!r}, expected {self.expects['model']!r}")
        if self.expects.get("fingerprint") not in (None, found["fingerprint"]):
            problems.append("the model's fingerprint is not the one this application was accepted with")
        if not found["release"]["fingerprint"]:
            problems.append("no release is active: nothing was approved to run")
        if self.expects.get("release") not in (None, found["release"]["fingerprint"]):
            problems.append("the active release is not the one this application was accepted with")
        if self.expects.get("stages") and found["stage"] not in self.expects["stages"]:
            problems.append(f"the use case is in {found['stage']}, this application works in {self.expects['stages']}")
        for key in ("case_templates", "actions"):
            missing = sorted(set(self.expects.get(key) or []) - set(found[key]))
            if missing:
                problems.append(f"missing {key}: {missing}")
        if problems:
            raise ContractError("; ".join(problems))
        return found

    def records(self, entity: str) -> List[Dict[str, Any]]:
        return self.need("GET", f"/objects?type={entity}&limit=500")["items"]

    def record(self, ident: str) -> Dict[str, Any]:
        return self.need("GET", f"/objects/{ident}")

    def request_action(self, case_template: str, root: str) -> Dict[str, Any]:
        """Ask the solution to handle one record. The Engine plans, checks every rule and either acts, waits for a
        person or refuses: the application decides none of it."""
        return self.need("POST", "/runs", {"case_template": case_template, "root": root})

    def run(self, run_id: str) -> Dict[str, Any]:
        return self.need("GET", f"/runs/{run_id}")

    def reviews(self) -> List[Dict[str, Any]]:
        return self.need("GET", "/reviews")["items"]

    def decide(self, review_id: str, approved: bool, comment: str = "") -> Tuple[int, Any]:
        """A person's decision, sent with that person's own token. An application's service identity is refused."""
        return self.call("POST", f"/reviews/{review_id}/decision", {"approved": approved, "comment": comment})

    def audit(self, run_id: str) -> Dict[str, Any]:
        return self.need("GET", f"/runs/{run_id}/audit")


# -- domain view: network intelligence (synthetic) -----------------------------------------------------------
def evidence_graph(app: Application, link_entity: str = "Association", party_entity: str = "Organization",
                   hypothesis_entity: str = "Hypothesis") -> Dict[str, Any]:
    """The parties and the links between them, each link with **how it is known**. Only recorded links become
    edges: nothing is inferred here, and closeness in the graph means nothing by itself."""
    nodes = {r["id"]: {"id": r["id"], "label": r["attributes"].get("name", r["id"])} for r in app.records(party_entity)}
    edges = []
    for row in app.records(link_entity):
        detail, a = app.record(row["id"]), row["attributes"]
        ends = {x["kind"]: x["id"] for x in detail["links"] if x["direction"] == "out"}
        if a["status"] not in CLASSES:
            raise ContractError(f"{row['id']}: a link must say how it is known, not {a['status']!r}")
        edges.append({"id": row["id"], "from": ends.get("first_party"), "to": ends.get("second_party"),
                      "kind": a.get("kind"), "classification": a["status"], "evidence_quality": a.get("evidence_quality"),
                      "source": a.get("source_reference") or None, "valid_from": a.get("valid_from") or None,
                      "valid_to": a.get("valid_to") or None, "note": a.get("note"),
                      "hypotheses": sorted(x["id"] for x in detail["links"] if x["direction"] == "in"
                                           and x["type"] == hypothesis_entity)})
    return {"nodes": sorted(nodes.values(), key=lambda n: n["id"]), "edges": sorted(edges, key=lambda e: e["id"]),
            "legend": {c: sum(e["classification"] == c for e in edges) for c in CLASSES},
            "caution": "A link is a statement about records, with its source and its certainty. No link, and no "
                       "distance between two parties, is evidence of wrongdoing."}


def investigative_summary(app: Application, case_id: str, run_id: Optional[str] = None) -> Dict[str, Any]:
    """What a reviewer can check line by line: the case, what is observed, what is inferred, what is only supposed,
    the competing explanations, and who decided what. Composed from records and from the audit trail; it states no
    conclusion about any person or organisation."""
    case, graph = app.record(case_id), evidence_graph(app)
    hypotheses = [app.record(x["id"]) for x in case["links"] if x["type"] == "Hypothesis"]
    resting = {x["id"] for h in hypotheses for x in h["links"] if x["type"] == "Association"}
    edges = [e for e in graph["edges"] if e["id"] in resting]
    out: Dict[str, Any] = {
        "case": case_id, "subject": case["attributes"].get("subject"), "status": case["attributes"]["status"],
        "observed": [e for e in edges if e["classification"] in ("observed_fact", "confirmed_assertion")],
        "inferred": [e for e in edges if e["classification"] == "inference"],
        "unresolved": [e for e in edges if e["classification"] == "unresolved_hypothesis"],
        "hypotheses": [{"id": h["id"], "statement": h["attributes"]["statement"], "basis": h["attributes"]["basis"],
                        "competing_explanation": h["attributes"]["alternative_explanation"]} for h in hypotheses],
        "evidence": [{"id": x["id"], **{k: v for k, v in app.record(x["id"])["attributes"].items()
                                        if k in ("title", "source", "quality", "status")}}
                     for x in case["links"] if x["type"] == "Evidence"],
        "decisions": [], "conclusion": "none: this summary reports records and decisions; it makes no finding about "
                                       "any person or organisation"}
    if run_id:
        trail = app.audit(run_id)
        out["audit"] = {"run": run_id, "verified": trail["verified"], "entries": len(trail["entries"])}
        out["decisions"] = [{"by": e["data"].get("reviewer"), "approved": e["data"].get("approved"),
                             "comment": e["data"].get("comment")} for e in trail["entries"] if e["event"] == "review.decision"]
    return out


# -- domain view: crisis management (synthetic) ---------------------------------------------------------------
def affected_resources(app: Application, incident_id: str) -> Dict[str, Any]:
    """What the records link to an incident: its area, the infrastructure and shelters of that area, and the team
    and equipment of its proposed assignment. "Potentially": this follows recorded links; it models no hazard."""
    incident = app.record(incident_id)
    out: Dict[str, Any] = {"incident": incident_id, "basis": incident["attributes"].get("information_basis"),
                           "source_verified": incident["attributes"].get("source_verified"), "area": None,
                           "infrastructure": [], "shelters": [], "teams": [], "equipment": []}

    def brief(ident: str) -> Dict[str, Any]:
        r = app.record(ident)
        return {"id": ident, "name": r["attributes"].get("name") or r["attributes"].get("task"),
                "status": r["attributes"]["status"], "links": r["links"]}

    for link in incident["links"]:
        if link["type"] == "AffectedArea":
            area = brief(link["id"])
            out["area"] = {k: area[k] for k in ("id", "name", "status")}
            for x in area["links"]:
                if x["type"] in ("Infrastructure", "Shelter") and x["direction"] == "out":
                    item = brief(x["id"])
                    out["infrastructure" if x["type"] == "Infrastructure" else "shelters"].append(
                        {k: item[k] for k in ("id", "name", "status")})
        if link["type"] == "Assignment":
            for x in brief(link["id"])["links"]:
                if x["type"] in ("ResponseTeam", "Resource") and x["direction"] == "out":
                    item = brief(x["id"])
                    out["teams" if x["type"] == "ResponseTeam" else "equipment"].append(
                        {k: item[k] for k in ("id", "name", "status")})
    out["caution"] = ("Read from recorded links on invented data. Not a forecast, not a dispatch and not validated "
                      "emergency guidance.")
    return out


def situation_update(app: Application, incident_id: str, run_id: Optional[str] = None) -> Dict[str, Any]:
    """An incident update that keeps four things apart: what is recorded as observed, what is assumed, what is
    predicted, and what is only recommended."""
    incident, around = app.record(incident_id)["attributes"], affected_resources(app, incident_id)
    basis = incident.get("information_basis")
    described = {"description": incident.get("description"), "people_at_risk": incident.get("people_at_risk")}
    out: Dict[str, Any] = {
        "incident": incident_id, "status": incident["status"],
        "facts": [described] if basis == "observed" and incident.get("source_verified") else [],
        "assumptions": [described] if basis != "predicted" and not incident.get("source_verified") else [],
        "predictions": [described] if basis == "predicted" else [],
        "recommendations": [{"assign": t["name"], "with": [e["name"] for e in around["equipment"]],
                             "note": "a proposal: the policy decides whether a person must approve it"}
                            for t in around["teams"]],
        "caution": around["caution"]}
    if run_id:
        run = app.run(run_id)
        out["run"] = {"id": run_id, "status": run["status"], "simulated": run["simulated"],
                      "performed": [s["action"] for s in run["steps"] if s["verdict"] == "allow"],
                      "waiting_for": (run.get("escalation") or {}).get("to"),
                      "refused": (run.get("escalation") or {}).get("details") if run["status"] == "escalated" else []}
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Synthetic reference client of the Autology application contract")
    p.add_argument("--url", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--use-case", required=True)
    p.add_argument("--token-env", required=True, help="the environment variable that holds the application's token")
    p.add_argument("view", choices=["connect", "evidence-graph", "affected-resources"])
    p.add_argument("record", nargs="?")
    a = p.parse_args(argv)
    app = Application(a.url, a.workspace, a.use_case, os.environ[a.token_env])
    try:
        out = {"connect": app.connect, "evidence-graph": lambda: evidence_graph(app),
               "affected-resources": lambda: affected_resources(app, a.record)}[a.view]()
    except ContractError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
