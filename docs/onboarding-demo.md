# Rapid onboarding demonstration (sandbox only)

> **Since the activation sprint (16 November 2026)** the Onboarding tab continues past the draft: agents and
> simulated tools, release, stored simulation runs and readiness of the draft. The complete journey, with a
> second template, is in [solution-demo.md](solution-demo.md). This page describes the first six steps.

One vertical slice of the onboarding experience, on synthetic data:

**business description → guided questions → solution proposal → visual review → engine validation → simulation →
readiness report**

What it is, plainly: the proposals come from the **sandbox architect**, a deterministic test double built on an
approved, industry-neutral template (request → review → approval → fulfilment → closure). **No language model is
involved** and nothing is sent anywhere; a real provider waits for the owner's decisions D7 and D10
([evaluation protocol](../planning/AUTOLOGY_AI_PROVIDER_EVALUATION_PROTOCOL.md)). Every step goes through the
versioned API; the engine validates, stores and decides. Nothing on the screen changes what runs, grants a
permission or calls another system.

## Start it

```bash
export AUTOLOGY_AUDIT_KEY=demo-key ACME_TOKEN_ADA=acme-ada ACME_TOKEN_HANA=acme-hana ACME_TOKEN_IVAN=acme-ivan \
       ACME_TOKEN_MARIA=acme-maria ACME_TOKEN_OLIVIA=acme-olivia ACME_TOKEN_LENA=acme-lena \
       NORTHWIND_TOKEN_NADIA=nw-nadia NORTHWIND_TOKEN_HANA=nw-hana
python -m autology platform examples/platform/platform.json --port 8700
# in another terminal
cd studio/web && npm ci && npm run build
AUTOLOGY_PLATFORM_URL=http://127.0.0.1:8700 npm start          # Studio on http://127.0.0.1:8960
```

These tokens are demonstration values for a local machine. The scripted version of the same journey is part of the
browser checks: `cd studio/web && npm run build && e2e/run.sh` (17 of its checks are this journey; screenshots in
`e2e/screenshots/desktop-onboarding-*.png`).

## Walk through it

1. Sign in to Studio with `acme-ada` (a workspace administrator).
2. **New** → template **Blank solution (guided onboarding)** → an identifier and a name → **Create in Draft**.
   The use case starts with an empty model.
3. Open it and choose the **Onboarding** tab.
4. **Describe**: keep the sample text or write your own (it must speak of requests, approval, a manager, a team or
   fulfilment for the template to apply; anything else gets a question back, not a guess). **Propose a solution**.
5. **Questions**: four questions come back for this template (approval threshold, approver role, handling role, fulfilment system).
   Answer some or all, then **Update the proposal with my answers**: a new revision of the same proposal is
   stored; the earlier one is kept.
6. **Review**: the graph shows the proposed entities and relationships with a dashed outline and the word
   *proposed*; what is already in the draft is drawn solid and marked *confirmed*. Below: the workflow (which
   action moves which state, and who decides), the rules and permissions in plain words, the described roles,
   agents and integrations, the assumptions and unknowns, and each proposed item with its confidence. Untick
   what you do not want. **Validate my selection with the engine**.
7. **Confirm**: the engine's strict loader answers. **Save … as a draft** stores the accepted items as a draft
   revision and records your review against the proposal. The draft is not active.
8. **Dry run** (step 6 of the screen; *Simulate the draft* leads there): **Run the simulation**. The engine's planner and rules run one synthetic case of the draft with
   stub tools. It stops where the model asks for a person; **Approve as … (simulated)** continues it. The audit
   trace of the simulation is shown. Nothing is stored and nothing outside the engine is called.
9. **Readiness** (step 9 of the screen): **Assess readiness for a pilot** shows the score per dimension with its calculation, the missing
   evidence and the blockers. For a new use case the blockers are the honest ones: no goal in what runs, no
   approved release, no stored run.

## What works through the UI, and what does not

| Step | State |
|---|---|
| Describe the business; get a proposal | Works, with the sandbox architect (template-based, not a language model) |
| Clarification questions; revise with answers; revision history | Works |
| Visual review: entities, relationships, workflow, rules, permissions; proposed against confirmed | Works |
| Engine validation of the selection; save as a draft; review recorded with provenance | Works |
| Simulate the draft with a simulated approval; audit trace | Works; a dry run with stub tools, not a stored run |
| Readiness report with blockers | Works for what runs now, for the saved draft and for a release that is not active; each report names its subject |
| Publish the draft, approve and activate a release | Works in step 7 of the same screen (and in the **Releases** tab); it needs a second person, by design |
| Run the published model as a stored simulation run | Works: agents and simulated tools are configured in step 5, released with the model, and runs are started in step 8 by a member who holds `run` |
| A description outside the template's vocabulary | Gets a clarification question only. A language model is needed for more (blocked on D7/D10) |
| Documents as input, industry packs, integrations to real systems | Not available |

The scripted journey takes under two seconds. That says nothing about a person: no timing with real users has
been measured, so the 30-minute onboarding target remains an aspiration, not a claim.
