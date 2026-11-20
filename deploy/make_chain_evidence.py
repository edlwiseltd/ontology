"""Write the chain evaluation's six replay scenarios and its element traces as evidence files.

    python deploy/make_chain_evidence.py planning/evidence/chain-trace-2026-11-20

A folder is dated and is never written again: ``planning/evidence/provenance-2026-11-19`` is what was reported on
19 November 2026 (before the trace showed the citations stored with older answers, GAP-113) and stays as it is.

It calls no provider and reads no credential: it runs the reserved briefs' hand-written reference answers, the
answers kept from the one authorised evaluation, a kept Studio journey and a model authored by hand through
``autology.chain_eval``. Nothing here is a person's review: where a scenario needs decisions that nobody recorded,
they are written below and labelled as illustrative.
"""

import json
import sys
from pathlib import Path

from autology import architect_eval, chain_eval

ROOT = Path(__file__).resolve().parent.parent
KEPT = ROOT / "planning" / "evidence" / "claude-eval-2026-11-17"
ILLUSTRATIVE = "illustrative decisions written with this evidence script; no person made them"

# scenario 4, on the reserved brief museum-loans: what a rejection and a correction do to what depends on them
REJECTION = {"by": ILLUSTRATIVE, "confirm": ["model:rule:R-VALUE", "model:case_template:loan_case"],
             "drop": ["model:entity:Borrower"]}


def _correction(proposal):
    rule = dict(next(i["value"] for i in proposal["items"] if i["id"] == "model:rule:R-VALUE"))
    rule["description"] = "The director approves every loan above the valuation limit, whoever the borrower is"
    return {"by": ILLUSTRATIVE, "confirm": ["model:case_template:loan_case"], "correct": {"model:rule:R-VALUE": rule}}


def _row(label, what, row):
    review, work = row.get("corrections") or {}, (row["C"].get("governed_work") or {})
    return {"scenario": label, "what": what, "decided_by": review.get("by"),
            "confirmation_rate": review.get("confirmation_rate"), "corrections": review.get("human_corrections"),
            "rejected_by_a_person": review.get("dropped"), "dependency_failures": review.get("dependency_failures"),
            "unresolved": review.get("not_applied_unconfirmed"),
            "A_architect": {"answered": row["A"].get("answered"), "elements": row["A"].get("elements_proposed"),
                            "inferred": row["A"].get("inferred_needing_confirmation")},
            "B_builder": {"manifest_valid": row["B"].get("valid"), "screens": row["B"].get("screens")},
            "C_engine": {"draft_accepted": row["C"].get("draft_accepted"), "simulation": work.get("default")},
            "trace_missing_by_link": ((row.get("trace") or {}).get("summary") or {}).get("missing_by_link")}


def build():
    museum = next(c for c in chain_eval.reserved() if c["id"] == "museum-loans")
    answer = chain_eval.reference(museum)
    kept = chain_eval.journey(KEPT / "ground-handling")
    venue = json.loads((ROOT / "examples" / "domains" / "venue_booking" / "model.json").read_text())
    manual, legacy = chain_eval.provenance_cases({"venue-booking": venue})
    six = [
        _row("1", "No element confirmed", chain_eval.run_case(museum, chain_eval.reference, {})),
        _row("2", "Only the recorded, attributable confirmations (a synthetic reviewer, written with the case)",
             chain_eval.run_case(museum, chain_eval.reference)),
        _row("3", "Hypothetical: every inferred element confirmed (a counterfactual; nobody confirmed them)",
             chain_eval.run_case(museum, chain_eval.reference, chain_eval.CONFIRM_ALL)),
        _row("4a", "A rejection, and what depended on the rejected element",
             chain_eval.run_case(museum, chain_eval.reference, REJECTION)),
        _row("4b", "A correction, validated again by the Engine",
             chain_eval.run_case(museum, chain_eval.reference, _correction(answer))),
        {"scenario": "5", "what": "A model authored by hand, with no architect proposal", **manual},
        {"scenario": "6", "what": "The same model as a legacy draft whose provenance was never established", **legacy},
    ]
    journey = {number: _row(number, chain_eval.SCENARIOS[number], chain_eval.run_case(kept["case"], kept["ask"], given))
               for number, given in (("1", {}), ("2", kept["recorded"]), ("3", chain_eval.CONFIRM_ALL))}
    replay = chain_eval.scenarios(architect_eval.cases(), chain_eval.replay(KEPT / "run2-after-correction"), {},
                                  "answers kept from the authorised evaluation of 17 November 2026")
    trace = chain_eval.run_case(museum, chain_eval.reference)["trace"]
    kept_trace = chain_eval.run_case(kept["case"], kept["ask"], kept["recorded"])["trace"]
    return {"protocol": chain_eval.PROTOCOL, "provider_calls": 0,
            "reading": "Three components are reported apart: A the AI Architect, B the Application Builder, C the Engine. "
                       "Acceptance by the Engine means the model loads and runs; it does not mean the model is right for "
                       "the business. No independent domain expert reviewed any model here. No total is computed.",
            "six_scenarios_reserved_brief_museum_loans": six, "kept_journey_ground_handling": journey,
            "kept_answers_run_2": replay["table"],
            "trace_museum_loans_recorded_decisions": trace, "trace_kept_journey_summary": kept_trace["summary"]}


def render(out):
    lines = [f"Chain evaluation, protocol {out['protocol']}. Provider calls: {out['provider_calls']}.", out["reading"], "",
             "Six scenarios on the reserved brief museum-loans (a hand-written reference answer, not a model)"]
    for row in out["six_scenarios_reserved_brief_museum_loans"]:
        if "provenance" in row:
            lines.append(f"  {row['scenario']:<3} {row['what']}: provenance {row['provenance']}; established by the Engine: "
                         f"{row['established_by_engine']}; may be published: {row['may_be_published']} ({row['why']}); "
                         f"draft accepted {row['draft_accepted']}; manifest valid {row['manifest_valid']}; A: {row['architect']}")
            continue
        lines.append(f"  {row['scenario']:<3} {row['what']}: confirmed {row['confirmation_rate']}; corrections {row['corrections']}; "
                     f"rejected {len(row['rejected_by_a_person'] or [])}; dependency failures {len(row['dependency_failures'] or [])}; "
                     f"C draft {'accepted' if row['C_engine']['draft_accepted'] else 'refused'}; "
                     f"B manifest {'valid' if row['B_builder']['manifest_valid'] else 'none'}; simulation {row['C_engine']['simulation'] or 'not run'}")
        for failure in row["dependency_failures"] or []:
            lines.append(f"        dependency: {json.dumps(failure, sort_keys=True)}")
    lines += ["", "The kept ground-handling journey (a real model's stored proposal; decisions recorded in the released model)"]
    for number, row in out["kept_journey_ground_handling"].items():
        lines.append(f"  {number:<3} {row['what']}: confirmed {row['confirmation_rate']}; dependency failures "
                     f"{len(row['dependency_failures'] or [])}; C draft {'accepted' if row['C_engine']['draft_accepted'] else 'refused'}; "
                     f"B manifest {'valid' if row['B_builder']['manifest_valid'] else 'none'}; simulation {row['C_engine']['simulation'] or 'not run'}")
    lines += ["", "Element traces, museum-loans with the recorded decisions (one line per element; a missing link is written as missing)"]
    for line in out["trace_museum_loans_recorded_decisions"]["elements"]:
        lines.append(f"  {line['element']}")
        for link in chain_eval.LINKS:
            lines.append(f"      {link:<17} {line[link]}")
    lines += ["", f"Kept journey, links missing per element kind of link: {json.dumps(out['trace_kept_journey_summary']['missing_by_link'])}",
              f"Kept journey, elements whose source and evidence are the label stored with the answer ({chain_eval.CITED_THEN}): "
              f"{out['trace_kept_journey_summary']['cited_at_the_time_not_rechecked']} of {out['trace_kept_journey_summary']['elements']}",
              "No total is computed."]
    return "\n".join(lines) + "\n"


def main(folder):
    out, target = build(), Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    (target / "six-scenarios-and-traces.json").write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n")
    (target / "six-scenarios-and-traces.txt").write_text(render(out))
    print(render(out))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "planning/evidence/chain-trace-2026-11-20")
