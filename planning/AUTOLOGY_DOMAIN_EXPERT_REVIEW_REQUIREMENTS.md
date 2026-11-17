# Autology — expert review requirements for the two demonstrator domains

*17 November 2026. Status: **requirements only.** No reviewer has been engaged, no review has taken place and no
score exists. The two parts are separate on purpose: different professions, different duties, different harms.
Neither demonstrator may be described as reviewed, validated or fit for use until its part has been carried out and
its result recorded.*

What a reviewer is given in both cases: the domain pack (`examples/domains/<pack>/blueprints/*.json`: model, rules,
agent, simulated tools, invented records), the stored runs with their audit trails, the screenshots of the Studio
journey, and the general form [AUTOLOGY_ARCHITECT_EXPERT_REVIEW_FORM.md](AUTOLOGY_ARCHITECT_EXPERT_REVIEW_FORM.md).
What a reviewer is told first: the model was written by an engineer as a template, not produced by a language
model, and everything it acts on is invented.

---

## Part A — Emergency operations (Autology Crisis Management, synthetic)

### Who

Two reviewers, independent of the project and of each other, each with command or coordination experience in a
civil-protection, fire-and-rescue or emergency-management organisation at regional level or above. At least one
with experience of flood response. Neither is asked to review software.

### What they must judge

| # | Question | Why it cannot be automated |
|---|---|---|
| A1 | Is the incident life cycle (received, validated, resources identified, allocation proposed, response assigned, updated) one a coordination centre would recognise? What is missing (triage, prioritisation between incidents, stand-down, hand-over)? | Completeness against a profession's practice |
| A2 | Is "a prediction is never grounds for assigning a team" right, too strict, or wrong for pre-positioning and precautionary evacuation? | A policy choice with safety consequences either way |
| A3 | Is the approval limit (people at risk) the right kind of trigger? Who really holds that authority, and under which legal instrument? | Authority is jurisdiction-specific |
| A4 | Does the model keep observed facts, reports, predictions and recommendations apart in the way the profession needs? Is an unverified report handled safely (the demonstrator does nothing with it)? | Doing nothing can itself be unsafe |
| A5 | Which decisions must never be automated, even as a proposal? | Professional and ethical judgement |
| A6 | What would make an incident update misleading to a commander? | Human factors |
| A7 | Which standards and doctrines apply (incident command structures, national frameworks, data standards for alerts and resources) and where does the model contradict them? | Regulatory knowledge |
| A8 | What evidence would be needed before any use in an exercise with real responders, and before any operational use? | Assurance path |

### What must be true before any claim beyond "synthetic demonstration"

* A hazard analysis of the whole system (not of the model alone), by a qualified person: failure modes include a
  wrong record, a late update, an approval that never arrives, a misleading summary.
* A named operational owner and a named accountable authority.
* Real integrations tested in a sandbox of the real systems, with their own acceptance.
* An exercise with practitioners, observed, with findings recorded.
* Legal review of responsibility for recommendations.

Explicit non-claims: the demonstrator forecasts nothing, dispatches nobody, warns nobody and gives no guidance. Its
"potentially affected resources" are recorded links between invented records.

---

## Part B — Financial compliance (Autology Network Intelligence, synthetic)

### Who

Two reviewers, independent of the project and of each other: one with experience of corporate compliance
investigations or internal audit (anti-fraud, anti-bribery or third-party due diligence), one with legal or
data-protection experience of investigations involving identifiable people. Neither is asked to review software.

### What they must judge

| # | Question | Why it cannot be automated |
|---|---|---|
| B1 | Is the case life cycle (opened, relationships extracted, pattern flagged, alternatives recorded, escalated, summarised) one a compliance function would recognise? What is missing (intake and triage, conflict-of-interest checks, legal privilege, closure and retention)? | Completeness against a profession's practice |
| B2 | Are the four classes of a link (observed fact, confirmed assertion, inference, unresolved hypothesis) the right ones, and is each sample link in the right class? | Evidential judgement |
| B3 | Is "the competing explanation is recorded before any escalation" sufficient protection against confirmation bias? What else is needed (a second analyst, a challenge step)? | Method |
| B4 | Is a materiality amount an acceptable trigger for flagging? What would it miss, and what would it wrongly flag? | Risk appetite |
| B5 | Does any wording in the model, the summaries or the screens read as an accusation or a finding about a person or a company? | Language and defamation risk |
| B6 | Which lawful basis, notice, access and retention rules would apply to such records about identifiable people, in the jurisdictions of interest? Is restricting bank-account records to one role the right control, and enough? | Law |
| B7 | Which decisions must never be automated, even as a proposal (reporting to an authority, suspension of a relationship, any adverse decision about a person)? | Professional and legal duty |
| B8 | What evidence would be needed before any use on real data? | Assurance path |

### What must be true before any claim beyond "synthetic demonstration"

* A data-protection impact assessment and a lawful basis, before a single real record is loaded.
* Written rules for sources: which may be consulted, by whom, and how provenance is recorded. No acquisition of
  personal records, no access to protected accounts, no surveillance, no law-enforcement database.
* A review of every template sentence a model or a summary can produce, by a lawyer.
* Human decision on every escalation and on every adverse step, with the reviewer's reasons recorded.
* A test, by the reviewers, that proximity in the graph is never presented as evidence.

Explicit non-claims: the demonstrator determines nobody's guilt, detects no fraud and proves nothing. Its "unusual
pattern" is a number in an invented record that exceeds a configured amount.

---

## Recording a review

Each reviewer fills the general form per proposal and answers the questions of their part in writing. Two
reviewers' forms are compared with `architect_eval_v2.agreement`; disagreements are kept, not averaged away. The
result is stored beside the evidence of the evaluation it belongs to, with the reviewers' roles (not their names,
unless they agree).
