# Autology audit — 13 November 2026

Independent reassessment of Autology at revision `fdfaf01`. Verified maturity: **47 / 100**.

| Report | For |
|---|---|
| [06 Executive summary](06_AUTOLOGY_EXECUTIVE_SUMMARY.md) | Leadership: verdict, risks, priorities, the ten questions answered |
| [01 Code audit](01_AUTOLOGY_CODE_AUDIT.md) | Inventory, architecture, verified capabilities, doc-vs-code, confirmed defects, Odoo assessment |
| [02 Test evidence](02_AUTOLOGY_TEST_EVIDENCE.md) | Test run, coverage, real-system checks, the 15 operational scenarios |
| [03 Maturity scorecard](03_AUTOLOGY_MATURITY_SCORECARD.md) | Method, domain scores, scores A/B/C, blocking conditions |
| [04 Gap register](04_AUTOLOGY_GAP_REGISTER.md) | Every gap with priority, cause, remedy, acceptance criteria and effort |
| [05 Roadmap to 95](05_AUTOLOGY_ROADMAP_TO_95.md) | Decisions, sequence, gates 80/90/95 |
| [`evidence/`](evidence/) | Every proof-of-concept and scenario script with its captured output |

**No application code was changed during this audit.** The audit was performed by AI agents (one of which wrote
the code); an independent human review is part of gate 95.

Re-run any piece of evidence from the repository root, e.g.:

```bash
PYTHONPATH=. AUTOLOGY_AUDIT_KEY=k python3 audit/evidence/reliability/s07_08_http.py
```
