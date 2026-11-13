# 06 — Executive summary

## The verdict in one paragraph

Autology is a well-built **prototype platform**, not yet a product that can be sold. Its design is sound and much
of it works and is tested: it models a business, lets AI agents plan and act within rules, sends important
decisions to people, and keeps a tamper-evident record. But when an outside system is slow or the server crashes at
the wrong moment, Autology can **pay the same bill twice**, or **report a payment as done when it was only
queued**. It has never run a real business process against a real company system, and never with a real AI model.
**Verified maturity: 47 out of 100.** The earlier estimate of 60 was based on a description; this audit tested
the actual software and found problems a description cannot show.

## What demonstrably works

- **The core idea works across industries.** The same software runs six different businesses (customer
  onboarding, manufacturing, healthcare referrals, aerospace scheduling, order fulfilment, motor insurance) without
  changes to its core.
- **Rules are enforced and decisions are recorded.** Mandatory steps, prohibitions, who-may-see-what, and human
  approvals are applied; the decision record cannot be quietly edited without detection, and it survives crashes.
- **AI mistakes are contained.** When the AI gives a broken or invalid answer, the system falls back to safe,
  rule-based planning instead of acting on it (tested with simulated AI).
- **It connects to the rest of a company's tools.** Data can be loaded from files, databases and web services with
  quality checks; dashboards (tested with Metabase), monitoring (Prometheus) and company sign-in (tested with
  Keycloak and a real browser) work.
- **It is engineered with care.** 408 automated tests all pass, covering 97% of the code; it installs as a Docker
  package that starts, backs up and restarts correctly in automated checks.

## What remains unverified

- Behaviour with a **real AI model** (no API key was available).
- Behaviour with a **real ERP or payment system**. There is no Odoo connector yet.
- **Restoring** from a backup as a procedure.
- **Capacity**: how many cases, users and transactions one server can handle.
- **Security assessed by people.** All reviewers in this audit were AI agents, and one of them wrote the code.

## The five most important risks

1. **Duplicate transactions.** A timeout, crash or retry can execute the same external action two or three times
   (reproduced: three payments for one claim). There is no "possibly done — check first" state.
2. **False confirmations.** Any positive reply from an outside system counts as success, even "queued" or an
   empty reply.
3. **Rule bypasses.** A user could approve their own work by triggering it through an automation; restricted
   values (e.g. credit limits) can be extracted through the what-if feature; users can cause actions on records
   they are not allowed to see.
4. **Data-quality traps.** A typo in a rule file silently removes a safety check; a missing linked record is
   treated as valid; one bad value from a tool can stop the server from restarting.
5. **No legal basis to distribute.** There is no software licence, so customers have no right to use it yet.

## Immediate engineering priorities

1. Make every external action **safe to retry and honest about uncertainty**: record each action before sending
   it, attach a unique transaction key, never retry an action whose outcome is unknown, and require real
   confirmation before reporting success. (≈ 5–7 weeks for one engineer.)
2. **Close the rule bypasses** and make rule files strict. (≈ 2 weeks.)
3. **Choose a licence**, and decide the deployment model (one installation per customer is recommended).

## What can realistically be commercialized today

- **Not** a product that takes real actions in customers' systems: not until priorities 1 and 2 are done.
- **Possible now, with care:** paid design partnerships or proofs of concept using **read-only or simulated
  actions** — modelling a customer's business, loading their data, rule checks, dashboards, what-if analysis and
  human-review workflows — under a written agreement, once a licence is in place.

## What must happen before claiming 95/100

1. Fix all critical defects, with automated proof: zero duplicates and zero false confirmations in a
   systematic failure-test suite, and zero rule bypasses in a security test suite (gate 80).
2. Run one real business process with one customer, first on a test system, then in production; validate two
   real AI providers; prove restore; measure capacity (gate 90).
3. Run a second customer process on a different system without changing the core; prove customer isolation; pass
   an independent penetration test; publish a release with support processes (gate 95).

**Rough timeline:** about 7–10 engineer-weeks to gate 80; a further 8–12 weeks plus the pilot's duration to gate
90; and 4–7 more weeks plus external assessments to gate 95. In practice that means **6–12 months with one or two
engineers**, governed mostly by how quickly pilots and assessments can be arranged. These are planning estimates,
not commitments.

---

## Answers to the ten audit questions

1. **Actual maturity today?** A capable, well-tested prototype: technically strong in modelling, rules and audit;
   not safe yet for real external transactions; no real-world validation.
2. **Capabilities missing from the PDF?** Everything delivered after it (Tier 3): data pipelines with quality checks,
   quarantine and lineage; PostgreSQL sources and reporting; a governed reporting database for dashboards;
   Prometheus metrics; company sign-in (OpenID Connect); a Docker image, verified online backups, a container
   smoke test in CI and a release workflow. Tests grew from 355 to 408.
3. **Confirmed defects?** Twenty-four were executed and reproduced, six of them critical (duplicate execution and
   false confirmation); see [01 §5](01_AUTOLOGY_CODE_AUDIT.md) and [04](04_AUTOLOGY_GAP_REGISTER.md).
4. **Not verifiable?** Real AI models, real ERP/payment systems, restore procedure, capacity, release publishing,
   isolation between customers, and any human-led security assessment.
5. **Genuinely domain-, ERP- and LLM-agnostic?** Domain: **yes**, demonstrated with six domains. ERP: **in design
   yes** (generic tool and data interfaces) **but unproven**: no ERP has been connected. LLM: **mostly** — the
   decision-making component is provider-neutral, but the chat assistant is built around one provider's message
   format and only one provider is implemented.
6. **Deployable in a real customer pilot today?** Only a **read-only or simulated-action** pilot. A pilot that
   executes real transactions should wait for gate 80.
7. **Main obstacles to commercialization?** Transaction safety, the rule bypasses, no licence, no real-world
   validation, no ERP connector, and no independent security review.
8. **Updated overall score?** **47 / 100** (technical framework 59, enterprise operational readiness 44,
   commercial readiness 41).
9. **Work and evidence needed for 95?** All P0 and High P1 items in the gap register, plus external evidence: a
   real production pilot, two validated AI providers, a second customer system, proven isolation, an independent
   penetration test, and a published, supported release. See [05](05_AUTOLOGY_ROADMAP_TO_95.md).
10. **Recommended sequence?** (1) Safe external execution; (2) close governance bypasses; gate 80;
    (3) hardening, real-AI evaluation, Odoo adapter, restore and load tests, first pilot; gate 90; (4) second
    system, isolation, independent assurance, productization; gate 95. Keep the existing core; add the missing
    "uncertain action" concept rather than rewriting.
