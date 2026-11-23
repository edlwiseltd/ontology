"""The document-to-ontology spike's benchmark: the existing offline proposal path against the document pipeline,
on the same frozen documents, with engineer-written reference labels.

    python deploy/make_docintel_benchmark.py [planning/evidence/document-ontology-spike/results]

No provider is called and no credential is read: the baseline is the sandbox architect (the template test double
the Engine already ships), the candidate is ``autology.docintel``. The reference labels were written by the
engineering team with the documents; they are synthetic, not an independent expert's judgment. Three documents were
used to fix generic reading bugs ("tuning"); the fourth was written and frozen before those fixes and is reported
apart. Results for each component are reported separately. No total is computed.
"""

import json
import sys
from pathlib import Path

from autology import architect, chain_eval, docintel, sandbox_ai
from autology.ai import ModelGateway, WorkspaceAI
from autology.modeling import validate

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "planning" / "evidence" / "document-ontology-spike" / "cases"
TUNING, HELD_OUT = ("pump-cell", "reclamations", "garden-plots"), ("clinic-bookings",)
K = docintel._key


def ratio(hit, whole):
    return {"hit": hit, "of": whole, "value": round(hit / whole, 3) if whole else None}


def extraction(labels, source, evidence_graph):
    """Candidate-level measures against the reference labels."""
    canon = {}
    for e in labels["entities"]:
        canon[K(e["name"])] = K(e["name"])
        for alias in e.get("aliases", []):
            canon[K(alias)] = K(e["name"])
    for a, b in labels.get("merges", []):
        canon[K(b)] = K(a)
    concepts = [n for n in evidence_graph["nodes"] if n["kind"] == "concept"]
    predicted = {canon.get(n["key"], n["key"]) for n in concepts}
    reference = {K(e["name"]) for e in labels["entities"]}
    unsupported = sorted(n["labels"][0] for n in concepts if canon.get(n["key"], n["key"]) not in reference)
    rel_ref = {(K(r["from"]), K(r["to"])): r["type"] for r in labels["relations"]}
    rel_pred = [(canon.get(r["from"].split(":", 1)[1], r["from"].split(":", 1)[1]), canon.get(r["to"].split(":", 1)[1], r["to"].split(":", 1)[1]), r["type"])
                for r in evidence_graph["relations"]]
    pairs = {(a, b) for a, b, _ in rel_pred}
    right = [(a, b, t) for a, b, t in rel_pred if (a, b) in rel_ref]
    reversed_ = [(a, b) for a, b, _ in rel_pred if (b, a) in rel_ref and (a, b) not in rel_ref]
    states_ref = {K(e): [docintel._snake(s) for s in v] for e, v in labels["states"].items()}
    states_pred = {canon.get(k.split(":", 1)[1], k.split(":", 1)[1]): v["readings"][0]["states"] for k, v in evidence_graph["states"].items()}
    rules_ref = [(r["kind"], K(r["about"])) for r in labels["rules"]]
    rules_pred = [(r["rule"], canon.get(r["concept"].split(":", 1)[1], r["concept"].split(":", 1)[1])) for r in evidence_graph["rules"]]
    # a rule's subject may carry a qualifier in the text ("a scrapped unit"): containment counts, and is said
    rules_hit = sum(1 for kind, about in rules_ref if any(k == kind and (about == p or about in p or p in about) for k, p in rules_pred))
    roles_pred = {n["key"] for n in evidence_graph["nodes"] if n["kind"] == "role"}
    roles_ref = {K(r) for r in labels["roles"]}
    merges_ref = {frozenset((K(a), K(b))) for a, b in labels.get("merges", [])}
    proposed = [frozenset(m.split(":", 1)[1] for m in mm["members"]) for mm in evidence_graph["merges"]]
    anchors = {a["id"]: a["text"] for a in source["anchors"]}
    stated = {(K(r["from"]), K(r["to"])): r["stated_in"] for r in labels["relations"]}
    accurate = cited = 0
    for r in evidence_graph["relations"]:
        key = (canon.get(r["from"].split(":", 1)[1], r["from"].split(":", 1)[1]), canon.get(r["to"].split(":", 1)[1], r["to"].split(":", 1)[1]))
        if key in stated:
            cited += 1
            accurate += any(stated[key].lower() in anchors.get(e["anchor"], "").lower() for e in r["evidence"])
    quotes_inside = all(e["quote"] in anchors.get(e["anchor"], "") for n in evidence_graph["nodes"] for e in n["mentions"])
    return {
        "entities": {"precision": ratio(len(predicted & reference), len(predicted)), "recall": ratio(len(predicted & reference), len(reference)),
                     "missed": sorted(reference - predicted), "not_in_reference": unsupported},
        "relations": {"precision": ratio(len(right), len(rel_pred)), "recall": ratio(len({(a, b) for a, b, _ in right}), len(rel_ref)),
                      "type_correct": ratio(sum(1 for a, b, t in right if rel_ref[(a, b)] == t), len(right)),
                      "direction_reversed": len(reversed_), "missed": sorted(f"{a} -> {b}" for (a, b) in rel_ref if (a, b) not in pairs)},
        "states": {"exact": ratio(sum(1 for e, v in states_ref.items() if states_pred.get(e) == v), len(states_ref)),
                   "missed": sorted(e for e in states_ref if e not in states_pred)},
        "rules": {"recall": ratio(rules_hit, len(rules_ref)), "note": "a rule's subject counts when one contains the other"},
        "roles": {"precision": ratio(len(roles_pred & roles_ref), len(roles_pred)), "recall": ratio(len(roles_pred & roles_ref), len(roles_ref))},
        "references": {"recall": ratio(len({K(r["label"]) for r in evidence_graph["references"]} & {K(r) for r in labels["references"]}), len(labels["references"]))},
        "merges": {"correct_proposals": sum(1 for p in proposed if p in merges_ref),
                   "incorrect_proposals": sum(1 for p in proposed if p not in merges_ref),
                   "expected_and_missed": sum(1 for m in merges_ref if m not in proposed),
                   "applied_without_a_person": 0},
        "evidence": {"relation_anchor_accuracy": ratio(accurate, cited), "every_quote_inside_its_anchor": quotes_inside},
        "parsing": {"flagged_paragraphs": sum(1 for a in source["anchors"] if a["flags"]), "skipped": evidence_graph["skipped"],
                    "ambiguities_left_for_review": len(evidence_graph["ambiguities"])},
    }


def ontology(proposal, labels):
    items = proposal["items"]
    reference = {K(e["name"]) for e in labels["entities"]} | {K(a) for e in labels["entities"] for a in e.get("aliases", [])}
    entity_keys = {K(" ".join(__import__("re").findall(r"[A-Z][a-z0-9]*|[a-z0-9]+", i["name"]))) for i in items if i["kind"] == "entity"}
    stated_only = architect.apply({"name": "x", "version": "0.1.0"}, [i for i in items if i["basis"] == "supplied"])
    everything = architect.apply({"name": "x", "version": "0.1.0"}, items)
    return {"proposed": len(items) + len(proposal["rejected"]), "accepted_by_engine": len(items),
            "refused_by_engine": [{"kind": r["kind"], "name": r["name"], "why": r["problem"][:120]} for r in proposal["rejected"]],
            "entities_matching_the_reference": ratio(len(entity_keys & reference), len({K(e["name"]) for e in labels["entities"]})),
            "elements_citing_a_paragraph": ratio(sum(1 for i in items if any(e["kind"] == "source" for e in i["evidence"])), len(items)),
            "elements_citing_the_brief_only": sum(1 for i in items if [e["kind"] for e in i["evidence"]] == ["brief"]),
            "inferred_needing_confirmation": sum(1 for i in items if i["basis"] != "supplied"),
            "questions": len(proposal["questions"]),
            "draft_valid_with_no_confirmation": bool(items) and validate(stated_only)["valid"],
            "draft_valid_if_everything_were_confirmed (counterfactual)": bool(items) and validate(everything)["valid"]}


def chain(case_id, text, proposal, decisions=None):
    """The existing chain harness on a proposal: builder and Engine results, reported apart."""
    case = {"id": case_id, "title": case_id, "brief": text[:4000], "synthetic": True}
    row = chain_eval.run_case(case, lambda _c: proposal, decisions if decisions is not None else {})
    work = row["C"].get("governed_work") or {}
    kept = (row.get("corrections") or {}).get("kept")
    return {"elements_in_draft": kept, "B_manifest_valid": row["B"].get("valid"), "B_deterministic": row["B"].get("deterministic"),
            "B_screens": row["B"].get("screens"), "C_draft_accepted": row["C"].get("draft_accepted"),
            "C_simulation": work.get("default") or ("not run" if not row["C"].get("draft_accepted") else work.get("why"))}


def with_states(source, text):
    """Illustrative only: the candidate's answer with one state ('recorded') given to each entity the text gives none,
    as if a person had answered the states questions that way. Nobody did; it shows what the Engine would then do."""
    answer, _ = docintel.to_answer(docintel.graph(docintel.extract([source])))
    for entity in answer["entities"]:
        if not entity["states"]:
            entity["states"] = ["recorded"]
    return docintel.propose([source], text[:4000], answer_override=answer)["proposal"]


def run():
    out = {"protocol": "docintel-benchmark-1", "provider_calls": 0, "aggregate": None, "cases": {}}
    for case_id in TUNING + HELD_OUT:
        text = (CASES / f"{case_id}.txt").read_text()
        labels = json.loads((CASES / f"{case_id}.labels.json").read_text())
        source = docintel.read_source(text, case_id, title=case_id, workspace="spike", ingested_at="frozen")
        evidence_graph = docintel.graph(docintel.extract([source]))
        candidate = docintel.propose([source], text[:4000])
        gateway = ModelGateway({"sandbox": sandbox_ai.SandboxArchitect()}, {"w": WorkspaceAI("sandbox", sandbox_ai.MODEL, ("synthetic",))})
        baseline = architect.propose(gateway, "w", text[:4000], data_classes=("synthetic",))
        illustrated = with_states(source, text)
        out["cases"][case_id] = {
            "set": "held out (frozen before the extractor's fixes)" if case_id in HELD_OUT else "tuning (generic reading bugs were fixed on it)",
            "language": source["language"], "paragraphs": len(source["anchors"]),
            "extraction": extraction(labels, source, evidence_graph),
            "ontology": {"baseline_sandbox_architect": ontology(baseline, labels), "candidate_document_pipeline": ontology(candidate["proposal"], labels)},
            "unmapped_findings": len(candidate["unmapped"]),
            "unmapped_examples": [u["why"][:110] for u in candidate["unmapped"]][:5],
            "application_and_engine": {
                "baseline, no confirmation": chain(case_id, text, baseline),
                "candidate, no confirmation": chain(case_id, text, candidate["proposal"]),
                "candidate, all confirmed (counterfactual)": chain(case_id, text, candidate["proposal"], chain_eval.CONFIRM_ALL),
                "candidate with one state per stateless entity, all confirmed (illustrative; no person)":
                    chain(case_id, text, illustrated, chain_eval.CONFIRM_ALL)},
            "illustrative_states": {"accepted_by_engine": len(illustrated["items"]), "proposed": len(illustrated["items"]) + len(illustrated["rejected"]),
                                    "refused": [{"name": r["name"], "why": r["problem"][:100]} for r in illustrated["rejected"]]}}
    return out


def render(out):
    lines = ["Document to ontology: offline benchmark (synthetic documents; engineer-written labels; no provider call; no total)", ""]
    for case_id, c in out["cases"].items():
        x, o = c["extraction"], c["ontology"]
        b, d = o["baseline_sandbox_architect"], o["candidate_document_pipeline"]
        v = lambda r: f"{r['hit']}/{r['of']}"  # noqa: E731
        lines += [f"{case_id} ({c['language']}, {c['paragraphs']} paragraphs; {c['set']})",
                  f"  extraction  entities P {v(x['entities']['precision'])} R {v(x['entities']['recall'])} | relations P {v(x['relations']['precision'])} "
                  f"R {v(x['relations']['recall'])}, type right {v(x['relations']['type_correct'])}, reversed {x['relations']['direction_reversed']} | "
                  f"states exact {v(x['states']['exact'])} | rules {v(x['rules']['recall'])} | roles P {v(x['roles']['precision'])} R {v(x['roles']['recall'])} | "
                  f"refs {v(x['references']['recall'])}",
                  f"              merges: {x['merges']['correct_proposals']} right, {x['merges']['incorrect_proposals']} wrong (proposed, none applied), "
                  f"{x['merges']['expected_and_missed']} missed | anchors right {v(x['evidence']['relation_anchor_accuracy'])} | "
                  f"flagged paragraphs {x['parsing']['flagged_paragraphs']}, skipped {len(x['parsing']['skipped'])}",
                  f"  ontology    baseline: {b['accepted_by_engine']} accepted / {b['proposed']} proposed, entities matching {v(b['entities_matching_the_reference'])}, "
                  f"citing a paragraph {v(b['elements_citing_a_paragraph'])}, questions {b['questions']}",
                  f"              candidate: {d['accepted_by_engine']} accepted / {d['proposed']} proposed, entities matching {v(d['entities_matching_the_reference'])}, "
                  f"citing a paragraph {v(d['elements_citing_a_paragraph'])}, questions {d['questions']}, unmapped {c['unmapped_findings']}",
                  f"              with one state per stateless entity (illustrative; no person): {c['illustrative_states']['accepted_by_engine']} accepted / "
                  f"{c['illustrative_states']['proposed']} proposed"]
        for label, r in c["application_and_engine"].items():
            lines.append(f"  chain       {label}: {r['elements_in_draft']} in the draft, manifest {'valid' if r['B_manifest_valid'] else 'none'} "
                         f"({r['B_screens']} screens), Engine {'accepts' if r['C_draft_accepted'] else 'refuses'} the draft, simulation: {str(r['C_simulation'])[:60]}")
        lines.append("")
    lines.append("Engine acceptance says a model loads; it says nothing of whether the model is right. No independent expert reviewed anything.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    target = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "planning/evidence/document-ontology-spike/results")
    target.mkdir(parents=True, exist_ok=True)
    result = run()
    (target / "benchmark.json").write_text(json.dumps(result, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    (target / "benchmark.txt").write_text(render(result))
    print(render(result))
