"""Prepare, locally, what an independent domain expert needs to review a proposed model: nothing more.

    python deploy/make_review_package.py inventory [FOLDER]      # the frozen artifacts, with hashes and what they lack
    python deploy/make_review_package.py form CASE FOLDER        # a blank form for one frozen artifact
    python deploy/make_review_package.py check FORM.json         # is a filled form complete and about what is frozen
    python deploy/make_review_package.py rehearse [FOLDER]       # the whole path on a synthetic case, synthetic judgments

It reads files of the repository and writes files. It calls no provider, reads no credential, contacts nobody and
sends nothing. It fills in no judgment of a real case: a blank form has every judgment empty, and the only filled
forms it writes are those of the rehearsal, on a synthetic case, by reviewers who are named as not being people.
No score is added up over the three components, and no threshold decides anything: the thresholds are the owner's
to agree before a review, and none is in this file.
"""

import csv
import hashlib
import io
import json
import sys
from pathlib import Path

from autology import proposal_review

ROOT = Path(__file__).resolve().parent.parent
KEPT = "planning/evidence/claude-eval-2026-11-17"
RUBRIC = "part-c-2026-11-20"
SCALE = (0, 1, 2, 3, "n/a")           # 0 wrong or harmful · 1 misleading or materially incomplete · 2 acceptable with corrections · 3 correct
SEVERITIES = ("none", "minor", "major", "critical")
UNCERTAINTY = ("low", "medium", "high")
ELEMENT_CRITERIA = {"S1": "existence", "S2": "naming and terminology", "S3": "content: properties, states, cardinalities, conditions, limits",
                    "S4": "basis: stated is stated, inferred is a reasonable inference", "S5": "authority of the deciding role",
                    "S6": "safety and operational consequence"}
MODEL_CRITERIA = {"M1": "completeness: what is missing", "M2": "process fidelity, exceptions included", "M3": "approvals reserved for a person",
                  "M4": "clarification questions asked", "M5": "inferred elements a member confirmed", "M6": "fitness of the generated application",
                  "M7": "contradictions within the model or with the brief"}
SYNTHETIC = "SYNTHETIC REHEARSAL: not a person, not a reviewer"
COMPONENTS = {"A": "AI Architect: fidelity, completeness, assumptions, evidence, semantic defects",
              "B": "Application Builder: deterministic manifest generation and conformance to the accepted model",
              "C": "Engine: structural validity, authorisation and enforceable constraints"}


def sha256(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def version(item):
    """What a judgment is about: the element's identity and content. A judgment of another content is stale."""
    held = json.dumps({"id": item["id"], "kind": item["kind"], "value": item.get("value")}, sort_keys=True, default=str)
    return hashlib.sha256(held.encode()).hexdigest()[:16]


def _counts(items):
    cited = [i for i in items if i.get("sources")]
    return {"elements": len(items), "stated": sum(1 for i in items if i.get("basis") == "supplied"),
            "inferred": sum(1 for i in items if i.get("basis") == "inferred"),
            "with_a_citation_stored_at_the_time": len(cited),
            "citation_labels": sorted({str(s) for i in cited for s in i["sources"]}),
            "citing_an_answer": sum(1 for i in items if any(str(s).startswith("answer") for s in i.get("sources") or [])),
            "with_structured_evidence_entries": sum(1 for i in items if i.get("evidence")),
            "with_a_rationale": sum(1 for i in items if i.get("rationale"))}


def _answer(case, path, kind, brief_from, decisions, limits, **more):
    held = json.loads((ROOT / path).read_text())
    return {"case": case, "kind": kind, "artifact": path, "sha256": sha256(path), "brief_from": brief_from,
            "brief_sha256": sha256(brief_from) if brief_from else None,
            "answered_by": {"provider": held.get("provider"), "model": held.get("model"), "request_id": held.get("request_id")},
            **_counts(held.get("items") or []), "refused_by_the_engine": len(held.get("rejected") or []),
            "questions": len(held.get("questions") or []), "assumptions": len(held.get("assumptions") or []),
            "decisions_on_record": decisions, "limits": limits, **more}


def inventory():
    """Every artifact a review could be about, as it is frozen in the repository. Held-out cases are listed by
    identifier and hash only: nothing of their content is copied here."""
    rows = []
    for path in sorted((ROOT / KEPT / "run2-after-correction").glob("*-[12].json")):
        case, number = path.stem.rsplit("-", 1)
        rows.append(_answer(f"run2:{case}:{number}", f"{KEPT}/run2-after-correction/{path.name}", "real model output (17 November 2026)",
                            f"autology/evaluation/{case}.json", "none: no person decided anything about this answer",
                            ["a V1 case: its expectations were written by the project, and the answer was scored against them",
                             "each element cites the brief as a whole, not a passage; no structured evidence entry (the field came later)",
                             "any 'all confirmed' result about it is a counterfactual"], reviewable="the original answer only"))
    journey = f"{KEPT}/ground-handling"
    rows.append(_answer("journey:ground-handling", f"{journey}/proposal-revision-2.json", "real model output (17 November 2026), revision 2 after answers",
                        None, "39 of 40 accepted by a project member in Studio (22 of 23 inferred); a member, not a domain expert",
                        ["the brief is inside the stored proposal; it was written by the project",
                         "12 inferred elements cite nothing; 28 cite the brief as a whole; none shows the answer it came from (GAP-081, fixed later); "
                         "no structured evidence entry (GAP-111). Nothing is reconstructed",
                         "the released model (active-model-release-3.json) is the model after a member's decisions: a review of it "
                         "is a review of a corrected model and must be reported as such"],
                        released_model={"artifact": f"{journey}/active-model-release-3.json", "sha256": sha256(f"{journey}/active-model-release-3.json")},
                        reviewable="the original proposal (revision 2), and separately the released model"))
    rows.append(_answer("canary:bicycle-rental", f"{KEPT}/canary/proposal.json", "real model output (17 November 2026), a first connectivity request",
                        None, "none", ["a three-sentence invented brief: too small to say anything about a domain"], reviewable="not proposed for review"))
    for path in sorted((ROOT / "autology" / "evaluation_reserved").glob("*.json")):
        rows.append({"case": f"reserved:{path.stem}", "kind": "held-out brief with a hand-written reference answer (not a model output)",
                     "artifact": f"autology/evaluation_reserved/{path.name}", "sha256": sha256(f"autology/evaluation_reserved/{path.name}"),
                     "decisions_on_record": "a synthetic reviewer written with the case; no person",
                     "limits": ["no real model has answered it: there is no architect output to review",
                                "content not copied into this package: it stays where it is"], "reviewable": "nothing yet"})
    for path in sorted((ROOT / "autology" / "evaluation_v2").glob("*.json")):
        rows.append({"case": f"v2:{path.stem}", "kind": "held-out case of the proposed protocol V2 (never run)",
                     "artifact": f"autology/evaluation_v2/{path.name}", "sha256": sha256(f"autology/evaluation_v2/{path.name}"),
                     "decisions_on_record": "none", "limits": ["V2 is proposed and not ratified (D30 g); no answer exists"], "reviewable": "nothing yet"})
    return {"rubric": RUBRIC, "components_reported_apart": COMPONENTS, "aggregate": None, "provider_calls": 0, "artifacts": rows,
            "reading": "An inventory of files. It says what exists and what each record lacks; it judges nothing."}


def _items(case):
    """The elements of one frozen artifact, and the row of the inventory that describes it."""
    row = next((r for r in inventory()["artifacts"] if r["case"] == case), None)
    if row is None or not str(row.get("reviewable", "")).startswith("the original"):
        raise SystemExit(f"{case}: not a frozen artifact proposed for review (see the inventory)")
    return row, json.loads((ROOT / row["artifact"]).read_text()).get("items") or []


def blank_form(row, items, reviewer=""):
    """Every judgment empty. Who reviews, on what basis and when is theirs to write."""
    return {"rubric": RUBRIC, "case": row["case"], "artifact": row["artifact"], "artifact_sha256": row["sha256"],
            "subject": "the original output as frozen: not a corrected model", "synthetic_rehearsal": False,
            "reviewer": {"name": reviewer, "role_and_organisation": None, "domain_experience": None, "independent_of_the_project": None,
                         "conflicts_disclosed": None, "appointed_by": None, "reviewed_on": None},
            "scale": "0 wrong or harmful · 1 misleading or materially incomplete · 2 acceptable with corrections · 3 correct · n/a; "
                     "empty when it cannot be judged",
            "element_criteria": ELEMENT_CRITERIA, "model_criteria": MODEL_CRITERIA, "severities": list(SEVERITIES),
            "elements": [{"id": i["id"], "version": version(i), "kind": i["kind"], "basis_shown": i.get("basis"),
                          "cited_at_the_time": i.get("sources") or "missing: the element cites nothing",
                          **{k: None for k in ELEMENT_CRITERIA}, "judgment": None, "cited_domain_basis": None, "rationale": None,
                          "severity": None, "uncertainty": None, "suggested_correction": None} for i in items],
            "model": {**{k: None for k in MODEL_CRITERIA}, "what_is_missing": None, "what_is_wrong": None},
            "note": "Filled by an independent reviewer. An empty field is never counted, and a judgment nobody gave is never computed."}


def check_form(form, items):
    """What stops a filled form from being used: who filled it, what it is about, and what a low rating owes."""
    problems = []
    who = form.get("reviewer") or {}
    for field in ("name", "role_and_organisation", "domain_experience", "conflicts_disclosed", "appointed_by", "reviewed_on"):
        if not who.get(field):
            problems.append(f"reviewer: {field} is empty")
    if who.get("independent_of_the_project") is not True:
        problems.append("reviewer: independence of the project is not declared")
    if SYNTHETIC in str(who.get("name")) and not form.get("synthetic_rehearsal"):
        problems.append("reviewer: a synthetic reviewer on a form that is not a rehearsal")
    current = {i["id"]: version(i) for i in items}
    seen = {}
    for row in form.get("elements") or []:
        seen[row.get("id")] = row
        if row.get("id") not in current:
            problems.append(f"{row.get('id')}: not an element of the frozen artifact")
            continue
        if row.get("version") != current[row["id"]]:
            problems.append(f"{row['id']}: the judgment is about another content than the one frozen")
        ratings = [row.get(k) for k in ELEMENT_CRITERIA]
        if any(r is not None and r not in SCALE for r in ratings):
            problems.append(f"{row['id']}: a rating outside the scale")
        low = any(r in (0, 1) for r in ratings)
        if row.get("severity") is not None and row["severity"] not in SEVERITIES:
            problems.append(f"{row['id']}: an unknown severity")
        if row.get("uncertainty") is not None and row["uncertainty"] not in UNCERTAINTY:
            problems.append(f"{row['id']}: an unknown uncertainty")
        if low and not row.get("rationale"):
            problems.append(f"{row['id']}: a rating of 0 or 1 without a rationale")
        if low and row.get("severity") in (None, "none"):
            problems.append(f"{row['id']}: a rating of 0 or 1 without a severity")
        if row.get("severity") == "critical" and not (row.get("rationale") and row.get("cited_domain_basis")):
            problems.append(f"{row['id']}: a critical defect without a rationale and a cited domain basis")
    problems += [f"{missing}: no row in the form" for missing in sorted(set(current) - set(seen))]
    overall = form.get("model") or {}
    if any(overall.get(k) is not None and overall[k] not in SCALE for k in MODEL_CRITERIA):
        problems.append("model: a rating outside the scale")
    return problems


def summarise(form):
    """Counts per criterion and the critical defects, listed apart. No average over criteria, no total, no verdict."""
    rows = form.get("elements") or []
    per = {k: {str(v): sum(1 for r in rows if r.get(k) == v) for v in SCALE} | {"not judged": sum(1 for r in rows if r.get(k) is None)}
           for k in ELEMENT_CRITERIA}
    return {"case": form.get("case"), "reviewer": (form.get("reviewer") or {}).get("name"),
            "synthetic_rehearsal": bool(form.get("synthetic_rehearsal")), "elements": len(rows), "ratings_per_criterion": per,
            "critical_defects": [{"id": r["id"], "rationale": r.get("rationale"), "cited_domain_basis": r.get("cited_domain_basis")}
                                 for r in rows if r.get("severity") == "critical"],
            "severities": {s: sum(1 for r in rows if r.get("severity") == s) for s in SEVERITIES},
            "aggregate": None, "verdict": None}


def disagreements(first, second):
    """Where two reviewers of the same frozen artifact differ. Kept for adjudication; never averaged away."""
    if (first.get("case"), first.get("artifact_sha256")) != (second.get("case"), second.get("artifact_sha256")):
        raise ValueError("the two forms are not about the same frozen artifact")
    names = [(f.get("reviewer") or {}).get("name") for f in (first, second)]
    if not all(names) or names[0] == names[1]:
        raise ValueError("two different, named reviewers are needed")
    theirs = {r["id"]: r for r in second.get("elements") or []}
    out = []
    for row in first.get("elements") or []:
        other = theirs.get(row["id"]) or {}
        apart = {k: [row.get(k), other.get(k)] for k in ELEMENT_CRITERIA
                 if isinstance(row.get(k), int) and isinstance(other.get(k), int) and abs(row[k] - other[k]) >= 2}
        if apart or "critical" in (row.get("severity"), other.get("severity")) and row.get("severity") != other.get("severity"):
            out.append({"id": row["id"], "ratings_two_or_more_apart": apart, "severities": [row.get("severity"), other.get("severity")]})
    return {"reviewers": names, "elements": len(first.get("elements") or []), "for_adjudication": out}


def rows_csv(form):
    """The element rows as a sheet a reviewer can fill without reading JSON."""
    columns = ["id", "version", "kind", "basis_shown", *ELEMENT_CRITERIA, "judgment", "cited_domain_basis", "rationale", "severity",
               "uncertainty", "suggested_correction"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in form["elements"]:
        writer.writerow({k: "" if row.get(k) is None else row.get(k) for k in columns})
    return out.getvalue()


def rehearsal_case():
    """A synthetic case kept apart from every held-out one: an engineer-written example model, read as stated elements."""
    path = "examples/domains/venue_booking/model.json"
    document = json.loads((ROOT / path).read_text())
    items = []
    for kind, section in proposal_review.SECTIONS.items():
        held = document.get(section) or {}
        pairs = held.items() if isinstance(held, dict) else [(None, v) for v in held]
        for name, value in pairs:
            label = name or (value.get("id") if kind == "rule" else f"{value.get('from')}-{value.get('type')}-{value.get('to')}")
            items.append({"id": f"model:{kind}:{label}", "kind": kind, "value": value, "basis": "supplied", "sources": []})
    row = {"case": "rehearsal:venue-booking", "artifact": path, "sha256": sha256(path)}
    return row, items


def _synthetic(form, letter, items):
    """Judgments made from the position of a row, so that they mean nothing about the model: the first row is a
    critical defect for one reviewer, the second is left unjudged, the third is where the two differ."""
    form["synthetic_rehearsal"] = True
    form["reviewer"] = {"name": f"{SYNTHETIC} ({letter})", "role_and_organisation": "none: synthetic", "domain_experience": "none: synthetic",
                        "independent_of_the_project": True, "conflicts_disclosed": "not applicable: synthetic", "appointed_by": "nobody: a rehearsal",
                        "reviewed_on": "2026-11-20"}
    for n, row in enumerate(form["elements"]):
        if n == 1:
            continue
        low = n == 0 and letter == "A" or n == 2 and letter == "B"
        row.update({k: 0 if low and k == "S3" else 3 for k in ELEMENT_CRITERIA})
        row.update({"judgment": "synthetic", "severity": ("critical" if n == 0 else "major") if low else "none",
                    "rationale": "synthetic rationale, written to exercise the form" if low else None,
                    "cited_domain_basis": "synthetic citation" if low else None, "uncertainty": "high" if low else "low"})
    return form


def rehearse():
    row, items = rehearsal_case()
    blank = blank_form(row, items)
    first, second = _synthetic(blank_form(row, items), "A", items), _synthetic(blank_form(row, items), "B", items)
    stale = json.loads(json.dumps(first))
    stale["elements"][3]["version"] = "0" * 16
    impostor = json.loads(json.dumps(first))
    impostor["synthetic_rehearsal"] = False
    return {"label": "SYNTHETIC REHEARSAL. It shows that the package is complete and the form usable. It is not a review, "
                     "it says nothing about any model, and no person took part.",
            "case": row, "elements": len(items), "provider_calls": 0,
            "a_blank_form_is_refused": check_form(blank, items)[:3],
            "filled_forms_accepted": [check_form(first, items), check_form(second, items)],
            "a_form_about_another_content_is_refused": check_form(stale, items),
            "a_synthetic_reviewer_outside_a_rehearsal_is_refused": check_form(impostor, items),
            "summaries": [summarise(first), summarise(second)], "disagreements": disagreements(first, second),
            "sheet_columns": rows_csv(blank).splitlines()[0]}


def render_inventory(held):
    lines = ["Frozen artifacts for an independent semantic review (an inventory of files; it judges nothing)", ""]
    for row in held["artifacts"]:
        lines.append(f"{row['case']}")
        lines.append(f"    what        {row['kind']}")
        lines.append(f"    file        {row['artifact']}")
        lines.append(f"    sha256      {row['sha256']}")
        if "elements" in row:
            lines.append(f"    elements    {row['elements']} ({row['stated']} stated, {row['inferred']} inferred); refused by the Engine: {row['refused_by_the_engine']}")
            lines.append(f"    citations   {row['with_a_citation_stored_at_the_time']} cite {row['citation_labels'] or 'nothing'}; "
                         f"{row['citing_an_answer']} cite an answer; {row['with_structured_evidence_entries']} have structured evidence entries")
        lines.append(f"    decisions   {row['decisions_on_record']}")
        lines.append(f"    reviewable  {row['reviewable']}")
        lines += [f"    limit       {limit}" for limit in row["limits"]]
        lines.append("")
    return "\n".join(lines)


def main(argv):
    command = argv[0] if argv else "inventory"
    if command == "inventory":
        held = inventory()
        if len(argv) > 1:
            target = ROOT / argv[1]
            target.mkdir(parents=True, exist_ok=True)
            (target / "inventory.json").write_text(json.dumps(held, indent=1, sort_keys=True) + "\n")
            (target / "inventory.txt").write_text(render_inventory(held))
        print(render_inventory(held))
    elif command == "form":
        row, items = _items(argv[1])
        form, target = blank_form(row, items), Path(argv[2])
        target.mkdir(parents=True, exist_ok=True)
        name = argv[1].replace(":", "-")
        (target / f"form-{name}.json").write_text(json.dumps(form, indent=1) + "\n")
        (target / f"form-{name}.csv").write_text(rows_csv(form))
        print(f"{len(items)} elements, every judgment empty: {target}/form-{name}.json and .csv")
    elif command == "check":
        form = json.loads(Path(argv[1]).read_text())
        problems = check_form(form, _items(form["case"])[1])
        print("\n".join(problems) or "complete")
        return 1 if problems else 0
    elif command == "rehearse":
        out = rehearse()
        if len(argv) > 1:
            target = ROOT / argv[1]
            target.mkdir(parents=True, exist_ok=True)
            (target / "rehearsal.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
        print(json.dumps({k: out[k] for k in ("label", "elements", "filled_forms_accepted", "disagreements")}, indent=1))
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
