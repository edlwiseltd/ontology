# Autology — legal decision package for D19 (GAP-031)

*15 November 2026. Prepared by engineering at the owner's direction ("proceed with legal-compliance preparation",
master directive V2). **This is not legal advice and not counsel's approval.** It collects verified facts and the
questions counsel must answer. GAP-031 stays **Partly fixed** and commercial distribution stays **blocked** until
closure criteria C1–C3 below are met. The options and engineering details of L1–L6 are in the
[GAP-031 section of the clarification note](AUTOLOGY_PARTIAL_GAPS_CLARIFICATION.md); this package does not repeat
them.*

## 1. Verified facts (repository at the date above)

| # | Fact | Evidence |
|---|---|---|
| F1 | The licence is proprietary, all rights reserved; the copyright holder is a **placeholder**: "[LEGAL ENTITY NAME — to be confirmed by the intellectual-property review]" | `LICENSE` lines 1–3 |
| F2 | The licence text states it is subject to the IP and third-party review and that counsel confirms the final text and entity | `LICENSE` last paragraph |
| F3 | The engine has no runtime dependency (Python standard library only); optional extras are `llm` (anthropic), `yaml` (PyYAML), `postgres` (psycopg) | `pyproject.toml` |
| F4 | A dependency-licence policy exists and is enforced in CI: permissive allowed; LGPL only optional, unmodified and dynamically imported after legal review; GPL/AGPL forbidden | `THIRD_PARTY_NOTICES.md`, `deploy/third_party_licences.json`, `tests/test_leg1_licences.py` |
| F5 | The default Docker image ships `psycopg` (LGPL-3.0) for PostgreSQL; an image without it builds and passes the smoke test in CI | `Dockerfile` (`ARG EXTRAS`), CI job `package` (runs 64–67 green) |
| F6 | The image's Python packages are pinned (`deploy/image-constraints.txt`); its Debian base packages are inventoried (`deploy/image-os-packages.txt`) and include copyleft packages typical of Debian | `deploy/` |
| F7 | Studio's shipped npm packages include LGPL-3.0 binaries (`sharp`/`libvips`, optional, installed by Next.js but never loaded: `images.unoptimized`) and one CC-BY-4.0 package (`caniuse-lite`, attribution) | `studio/web/licences.json` (count by licence: MIT 33, Apache-2.0 16, ISC 10, LGPL-3.0-or-later 10, mixed Apache/LGPL 4, BSD-3-Clause 2, CC-BY-4.0 1) |
| F8 | Every commit in the repository (104 of 104 at this date) was produced with an AI coding assistant: git author "Claude", with a `Co-Authored-By` line naming the assistant; commits were pushed through the owner's GitHub account | `git log --format='%an'`, `git log --format='%B'` |
| F9 | The repository contains synthetic examples only; no customer data, no third-party proprietary standards | `examples/`, audit of 15 Nov §7 |
| F10 | No package or image has been distributed; no release tag exists | `git tag` (empty); decision PROD |

## 2. Questions for counsel

L1–L6 as listed in the [clarification note](AUTOLOGY_PARTIAL_GAPS_CLARIFICATION.md#gap-031--no-licence-redistribution-terms-undefined-high-blocks-customer-use):
legal entity (L1), licence text (L2), LGPL driver in the default image (L3), Debian base packages (L4), dependency
policy (L5), Studio npm packages (L6). Added by this package:

| ID | Question | Why it matters | Facts |
|---|---|---|---|
| **L7** | How do the AI-assisted authorship of the code base and the AI provider's terms affect ownership and the ability to license it (copyright subsistence, chain of title, warranties the licence may give)? | The licence asserts "all rights reserved" by the copyright holder; F8 shows the authorship model | F1, F8 |
| **L8** | Which notices must accompany each distributed artefact (wheel, Docker image, Studio build), and who maintains them? | `THIRD_PARTY_NOTICES.md` covers Python; Studio has `licences.json`; the image needs the Debian notices if distributed (L4) | F4–F7 |
| **L9** | Do the terms of any AI model provider configured by a customer (D7/D10) impose obligations on Autology's distribution or on outputs? | Multi-provider architecture approved in principle (D7/D10) | decision register |

## 3. Closure criteria (unchanged; all required)

- **C1** counsel's written sign-off on the licence text and the legal entity (L1, L2, and L7 for ownership),
  recorded in the decision register; `LICENSE` updated.
- **C2** written decisions on L3, L4 and L6 (and L8 for notices), applied to the Dockerfile, the Studio build and the
  notices.
- **C3** `tests/test_leg1_licences.py` and the CI image licence checks pass with the final texts and the chosen
  images.

## 4. What engineering can do once counsel answers (not before)

Update `LICENSE` and the notices; switch the default image (L3); strip optional `@img/*` packages from a Studio
deployment artefact (L6); add notice bundles per artefact (L8). None of these is started, because each depends on an
answer above.
