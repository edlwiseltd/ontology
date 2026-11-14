# Autology — implementation backlog

*14 November 2026. The backlog in priority order. Sequencing, estimates and acceptance criteria per story are in the
[release roadmap](AUTOLOGY_RELEASE_ROADMAP.md); R1 stories and their evidence in the
[R1 completion report](AUTOLOGY_R1_COMPLETION_REPORT.md); defects in the [defect register](AUTOLOGY_DEFECT_REGISTER.md).*

## Done (R1)

GOV-1–5, MOD-1–4, ACT-1–6, ISO-1–4, LEG-1, ENG-1, entry-point and fault-injection matrices; earlier: GAP-008,
GAP-015, workspaces and router.

## Next, in order

| # | Item | Release | Why now | Blocked by |
|---|---|---|---|---|
| 1 | API-1, API-2: OpenAPI 3.1 contract from one route table, `/api/v1`, contract tests | R2 | Studio and every client build against it (master §2A) | — |
| 2 | ARC-0: split the service behind the route table (GAP-026); MIG-1 transactional migrations (GAP-041) | R2 | The service grew to 2,119 lines in R1; every R2 feature adds to it | — |
| 3 | QA-1: mypy, ruff, pip-audit, pinned constraints (GAP-025, GAP-040); raise the coverage margin (95.9 % vs 95 %) | R2 | Gate 90.7; safer refactoring | — |
| 4 | REL-1, REL-2, REL-4: releases, server-side gates, full diff | R2 | Nothing from Studio may go live without them | — |
| 5 | ADM-1, ADM-2: workspace administration with second-approver grants | R2 | Dynamic workspaces | D11 |
| 6 | AI-1: two model adapters | R2 | The architect needs a model | D7 keys, D10 |
| 7 | ARC-1–4, BP-1, SEC-A, REL-3 | R2 | Acceptance criteria 3, 4, 5 | 6 |
| 8 | STU-1–6 (separate application) | R2 | User-facing Studio | D9, 1 |
| 9 | XL-1–4, DOC-1, PRV-1, ORG-1/2, SYS-1, ISO-5, HARD-1 | R3 | Onboarding | 4 |
| 10 | AGF-1–3, INT-1–4, HRM-1 | R4 | Agents and integrations | Odoo sandbox access (D6) |
| 11 | WUI-1–4 | R5 | Operational UI | 1 |
| 12 | RDY-1, OPS-1–3, SEC-1, VAL-1, REL-5, DOC-2, COM-1 | R6 | Gates 90 and 95 | external parties |
