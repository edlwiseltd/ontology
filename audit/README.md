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

## Status since the audit

The reports above describe revision `fdfaf01` and are left unchanged. Gaps fixed afterwards:

| Gap | Fix | Evidence |
|---|---|---|
| GAP-008 Two concurrent runs on the same record both execute | One open run per record (start, automation, confirmed proposal); approving is refused while duplicates exist | `tests/test_one_run_per_record.py`; `evidence/reliability/s11_concurrency.py` 11a now shows one run and one payment (was two) |
| GAP-015 (Console only) Negative `Content-Length` | The Console's own server refuses it (411); the engine is still affected | `tests/test_console.py` |

Still open from the same script: 11b/11c (GAP-009, a run resumed after review does not re-check data changed while
it waited).
