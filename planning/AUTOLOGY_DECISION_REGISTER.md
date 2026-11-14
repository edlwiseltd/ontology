# Autology — decision register

*14 November 2026. One place for every decision that belongs to the owner (master prompt Rule 6). **Approved**
means the owner said so explicitly; the source is quoted. **Applied default** means an engineering default is in
place and can be changed, pending the owner's confirmation. **Pending** means nothing may be assumed.
Recommendations are never authorisations: none of these allows a production deployment, production ERP writes or
unrestricted external access.*

## 1. Approved by the owner

| ID | Decision (owner, 14 Nov 2026) | Applied as | Consequences |
|---|---|---|---|
| D1 | "Design for multi-tenancy while supporting dedicated, isolated customer deployments. Start with isolated pilot deployments." | ADR-001: a store per use case, platform router; pilots run as one workspace per deployment | Multi-tenant hosting needs the R2 administration API before workspace admins configure their own use cases |
| D4 | "Enforce the intersection of the initiating user's effective permissions, agent-specific permissions, workspace boundaries, and governance policies. Scheduled agents must use explicitly authorised service identities with least privilege." | GOV-3, GOV-5: requester ∩ agent roles, `run_as` grants, `service_identities` required for automations | Every automation run names an identity; a server without one refuses to start |
| D5 | "Design for proprietary commercial distribution, subject to intellectual property and third-party licensing review." | LEG-1: `LICENSE`, `THIRD_PARTY_NOTICES.md`, CI licence check | Legal sign-off, the legal entity's name and the LGPL/MPL components in the image remain for counsel |
| D6 | "Prepare Odoo 18 Enterprise sandbox integration. Do not enable production ERP writes until external action safety requirements have passed." | R4 INT-2/INT-3 on a sandbox only | Production ERP writes stay disabled even though the repository's action-safety tests pass; enabling them needs a new, explicit owner decision |
| D7 | "Preserve provider independence and validate at least two model adapters." | R2 AI-1 | Needs API access to two providers (keys from the owner) |
| XL | "openpyxl is approved as a dependency, subject to dependency security and license checks." | See §3 evaluation; adopted in R3 XL-1 | Pin `openpyxl==3.1.5` with `defusedxml==0.7.1` |
| SEQ | Release sequence R1–R6 (master execution prompt, Part 12) | [Roadmap](AUTOLOGY_RELEASE_ROADMAP.md) | Three dependency-order choices documented in the roadmap §8 |
| PROD | "No production deployment is authorised at this stage." | Nothing deployed; no production configuration changed | Stays until revoked explicitly |

## 2. Pending, or applied defaults awaiting confirmation

| ID | Decision | Status | Recommendation | Consequence of waiting |
|---|---|---|---|---|
| D2 | Operational store (SQLite / PostgreSQL) | Pending | SQLite for the isolated pilots; PostgreSQL when a shared deployment or HA needs it | None for R2; blocks OPS-3 |
| D3 | Encryption at rest | Pending | Encrypted volumes per pilot deployment, documented as a deployment requirement | Blocks gate 4.2 credit and some customers' security reviews |
| D8 | Actions without a declared side effect are non-idempotent (audit recommendation) | **Applied default**, owner confirmation pending | Keep: never retry an unknown outcome automatically | Changing it would allow automatic retries of unknown outcomes |
| D9 | Studio technology and repository layout | Pending | TypeScript single-page app in `studio/`, its own build, image and release, client generated from the OpenAPI contract | Blocks STU-1 (R2) |
| D10 | Model providers for the architect, and whether workspace briefs and documents may be sent to them (data residency) | Pending | Two providers; a per-workspace setting, off by default for documents | Blocks AI-1 and ARC-1 (R2) |
| D11 | Second approver for grants and promotions when a workspace has one administrator | Pending | A named external approver role | Blocks ADM-1 completion for small customers |
| D12 | Credential scope per workspace by environment prefix (ISO-4) | **Applied default**, owner confirmation pending | Keep until a secret store is chosen (D13) | — |
| D13 | Secret store for integration credentials (environment variables today) | Pending | Per-workspace secret store before customers configure connectors themselves | Blocks workspace self-service integrations (R4) |
| D14 | Cross-use-case sharing inside a workspace | **Applied default: none**, owner confirmation pending | Keep none; add explicit, authorised sharing in R2 if a customer needs it | — |
| D15 | Production ERP writes after the sandbox (R4) | Pending, not authorised | Separate decision per customer and system, after sandbox evidence | Production writes stay disabled |
| D16 | Real customer pilot and data | Pending | One process, test or staging system first | Gates 90.4 and 95.5 cannot be passed without it |

## 3. Evaluation: `openpyxl` (for decision XL)

| Check | Result | Evidence |
|---|---|---|
| Licence | MIT; its dependency `et-xmlfile` MIT; `defusedxml` PSF-2.0 | Package metadata; `deploy/third_party_licences.json` (openpyxl, et-xmlfile listed; defusedxml to be added with XL-1) |
| Known vulnerabilities | None found for `openpyxl==3.1.5`, `et-xmlfile==2.0.0`, `defusedxml==0.7.1` | `pip-audit -r` on 14 Nov 2026 (PyPI advisory data) |
| XML attacks (entity expansion, external entities) | `openpyxl` uses `defusedxml` automatically when installed | `openpyxl.xml.DEFUSEDXML` is `True` with it installed |
| Macros and formulas | `openpyxl` neither runs macros nor evaluates formulas; XL-2 refuses `.xlsm`, loads with `read_only=True, data_only=True` | Design (XL-2) |
| Zip bombs, huge sheets | Not prevented by `openpyxl`: XL-2 checks compressed and uncompressed sizes and row/column limits before parsing | Design (XL-2) |
| Version management | Pin exact versions in the optional extra `excel`; pip-audit in CI (QA-1) | Design |

Verdict: the conditions of the approval are met for adoption in R3, provided `defusedxml` ships with it and the
XL-2 limits are implemented.
