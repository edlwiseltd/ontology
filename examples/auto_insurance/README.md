# Auto-insurance claims: a Minimum Viable Ontology

The smallest model of motor claims that still delivers value: **claim → repair shop → payment**, plus the
policy and vehicle the claim depends on. It uses all five ontology elements and all three layers; see
[`docs/ontology-concepts.md`](../../docs/ontology-concepts.md) for how each concept maps to Autology.

| Element | Here |
|---|---|
| Object types | `Claim` (also called `Case` and `Incident`), `Policy`, `Vehicle`, `RepairShop`, `Payment` |
| Properties | `Claim.amount`, `Claim.fraud_score`, `Policy.deductible`, `Policy.holder` (PII), `Vehicle.age_years`... |
| Link types | `Claim -against-> Policy`, `-concerns-> Vehicle`, `-repairedAt-> RepairShop`, `-settledBy-> Payment` |
| Action types | `assess_fraud`, `approve_claim`, `reject_claim`, `pay_claim` |
| Functions | `Claim.payout` = amount less deductible, capped at the coverage limit; `Claim.late_report` |

Rules: an investigator reviews suspicious approvals and every rejection; a claims manager reviews payouts of
20,000 or more; a claim scored as fraud is never paid; only claims handlers see the policy holder's name.

```bash
python -m autology validate examples/auto_insurance/ontology.json --data examples/auto_insurance/data.json
python -m autology score examples/auto_insurance/ontology.json --tools examples/auto_insurance/tools.json \
    --data examples/auto_insurance/data.json      # 97/100; the pilot scope gate fails on purpose: it is an MVO
```

The three claims in `data.json` take three different paths:

| Claim | Facts | What happens |
|---|---|---|
| CL-1 | 3,200, reported after 2 days | scored clear, approved for 2,700 (the 500 deductible applied), paid |
| CL-2 | 48,000 total loss | scored suspicious: an investigator approves; the payout is capped at the 40,000 limit, so a claims manager approves the payment too |
| CL-3 | 35,000, reported after 75 days | scored as fraud: referred, only an investigator can reject it, and it can never be paid |

`tools.json` simulates the fraud engine, claims system and payments as decision tables; replace any of them
with an `http` or `python` tool to connect the real system. `server.json` runs it as a service with a claims
handler (hana), an investigator (ivan), a claims manager (maria) and an automation that starts settling every
newly reported claim. Record what happened after a decision (`POST /api/runs/{id}/outcomes`) and
`GET /api/outcomes` suggests which rules to tighten: the dynamic layer.
