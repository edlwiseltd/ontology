# Autology — runtime separation and deployment architecture: assessment for D35 (GAP-103)

*17 November 2026. Status: **assessment and migration plan. No infrastructure was changed.** The application
runtime is still built and served with Studio. This document says what that means, what the target is, and in
which order to get there. Decision D35 d (the runtime is served by the same web project as Studio) is an applied
engineering default awaiting the owner's confirmation; this is the material to confirm or change it.*

## 1. What exists today (verified in the code)

| Aspect | State today | Where |
|---|---|---|
| **Code** | The runtime imports nothing of Studio's; Studio embeds it in one place, the designer's preview. A test keeps both true | `studio/web/runtime/`; `studio/web/tests/runtime.test.ts` |
| **Origin** | **Shared.** Studio (`/`) and every application (`/run/<workspace>/<use-case>`) are pages of one Next.js project on one origin | `studio/web/app/` |
| **Authentication** | The runtime has its own sign-in screen. It accepts the **same member tokens** as Studio: a token is not issued for one plane | `runtime/RuntimeApp.tsx`; the platform's member tokens |
| **Token management** | Each side keeps its token under its own key in the tab's session storage (`autology-app-token`, `autology-studio-token`), never in a cookie or in local storage. Both keys live in the **same origin's** storage | `runtime/client.ts`; `lib/api.ts` |
| **Session isolation** | By convention, not by the browser: any script running on the origin can read both keys in a tab that used both. The designer opens an application in a new tab without an opener (`rel="noreferrer"`), which starts with empty session storage (tested) | `components/ApplicationDesigner.tsx` |
| **Content security policy** | One policy for both: same-origin connections only, no framing, no objects, no base URI; **inline scripts are allowed** (`'unsafe-inline'`, needed by the framework's hydration until a nonce is used) | `studio/web/next.config.ts` |
| **API routing** | One relay forwards `GET` and `POST` under `/platform/` (administration) and `/w/` (use cases) with three headers. The runtime only ever asks `/w/<workspace>/u/<use-case>/api/v1/…` (tested), but the relay it sits behind **also reaches administration** | `lib/forward.ts` |
| **Deployment isolation** | None between Studio and runtime: one build, one process, one release cadence. The Engine (platform and use-case APIs) is a separate process, reached only through the relay | `deploy/` |
| **Application versioning** | A design has revisions and is bound to a configuration; the runtime code has no version of its own separate from Studio's | `autology/applications.py` |
| **Tenant boundaries** | Enforced by the Engine: every path names a workspace and a use case, a token belongs to one workspace, another workspace answers 401, 403 or 404. The browser side adds nothing to this and removes nothing | `autology/platform.py`; `tests/test_xdom1…`, `test_app1…`, `test_app2…` |

**What is and is not a security boundary today.** The Engine's authentication, permissions, rules and workspace
isolation are. The separation between Studio and the runtime in the browser is **not**: it is a code-organisation
property with tests. A designer who is also an application user in one tab holds both tokens on one origin.

## 2. Risks of the shared origin

| # | Risk | Severity today | Why it is not worse |
|---|---|---|---|
| R1 | A script-injection flaw in either side reads the other side's token | Medium | Neither side turns data into markup or code (source tests); manifests are plain text validated by the Engine; no token is in a cookie |
| R2 | The runtime's network path reaches administration routes through the shared relay | Medium | The Engine authorises every call; an application user's token has no office. A stolen administrator token used in the runtime tab is the case that matters |
| R3 | A token is valid on both planes | Medium | Tokens expire; the Engine rate-limits failed sign-ins; least privilege by grant |
| R4 | Studio's release cadence is the runtime's: a designer-tool change redeploys every business application | Low for security, real for operations | — |
| R5 | One content security policy must fit both, so it is as loose as the looser side needs | Low | It already allows same-origin connections only |
| R6 | A business user's address is under the design tool's host name | Low | Presentation only |

None of these lets a caller exceed what the Engine grants. They widen what a **browser-side** compromise could
reach.

## 3. Target architecture

    ┌────────────────────────┐   ┌──────────────────────────┐
    │ Studio Control Plane   │   │ Application Runtime Plane │
    │ design, releases,      │   │ renders a manifest;       │
    │ members, grants        │   │ records, runs, reviews    │
    │ origin A               │   │ origin B                  │
    └───────────┬────────────┘   └────────────┬─────────────┘
                │ /platform/ + /w/            │ /w/<ws>/u/<uc>/api/v1/ only
                ▼                             ▼
    ┌───────────────────────────────────────────────────────┐
    │ Engine Governance Plane                               │
    │ authentication, permissions, rules, runs, audit,      │
    │ releases; the only place where anything is decided    │
    └───────────────────────────────────────────────────────┘

| Plane | Holds | Never holds |
|---|---|---|
| **Studio Control Plane** | Designer, release and member administration | A business user's session |
| **Application Runtime Plane** | The renderer; one relay that forwards the versioned API of use cases | Any route of administration; any code of Studio |
| **Engine Governance Plane** | Everything that decides | Any page |

**Separate origins, separate deployments, or both?**

| Option | Closes | Cost | Assessment |
|---|---|---|---|
| A. Keep one origin, one deployment | Nothing | None | Acceptable for simulation and demonstrations. Not for production |
| B. **Separate origins**, one build artefact started twice with a different role | R1, R2, R5, R6 | Small: a start-up setting that selects the pages and the relay rule served; two host names | **Recommended first step.** The browser, not a convention, then separates the sessions |
| C. Separate origins **and** separate deployments (two packages, two pipelines) | R1, R2, R4, R5, R6 | Medium: split the web project, version the runtime on its own, publish a compatibility statement with the manifest version | Recommended before production |
| D. C, plus tokens issued for one plane | R3 as well | A change to identity (token audience or scope): an owner decision, not part of this assessment | Decide with the identity roadmap; **not started** (IAM-2, IAM-4 to IAM-6 are not to be implemented early) |

Both, in two steps: B, then C. D is a separate decision.

## 4. Migration plan (nothing below has been done)

| Step | Change | Regression test that must pass |
|---|---|---|
| 0 | **Today.** Pin what holds | Runtime imports nothing of Studio's; own token key; asks only `/w/<ws>/u/<uc>/api/v1`; opened without an opener; one address set once (`runtime.test.ts`) |
| 1 | A relay rule for the runtime plane: forward only `/w/<ws>/u/<uc>/api/v1/…`, never `/platform/`, never the unversioned API | **Written and tested, not wired:** `runtimeForwardable` in `lib/forward.ts`; `forward.test.ts` checks it and checks that no route uses it yet |
| 2 | A start-up role (`studio` or `runtime`): the runtime role serves `/run/…` and the narrow relay only; the Studio role keeps the designer's embedded preview and stops serving `/run/…` | Per role: the other plane's pages answer 404; the runtime role's relay refuses `/platform/…` |
| 3 | Two origins. The designer's "open the application" link points to the runtime origin. A stricter policy on the runtime origin (no inline script once a nonce is in place) | Browser journey on two origins: the three demonstrations pass unchanged; a token stored on one origin is absent from the other |
| 4 | The Engine names the allowed runtime origins per workspace, if the browser ever calls it directly (today it does not: both planes use a same-origin relay) | No cross-origin request is accepted from an origin not named |
| 5 | Split the package: the runtime is versioned on its own and states the manifest versions and Engine API versions it renders | Compatibility test: runtime version × manifest version; an unsupported manifest version is refused with a reason |
| 6 | (Owner decision) Tokens for one plane | A runtime token is refused by administration routes, whatever its holder's office |

Steps 1 to 3 need no Engine change and no data migration. Each step is reversible by configuration.

## 4a. Contracts of the target (added 19 November; designed, not deployed)

| Contract | Design | State |
|---|---|---|
| **Separate origins** | Studio on origin A, applications on origin B; the designer's "open the application" link points to B | Not deployed |
| **Restricted application relay** | Origin B forwards `GET` and `POST` under `/w/<workspace>/u/<use-case>/api/v1/` only: no `/platform/`, no unversioned API | Rule written and tested (`runtimeForwardable`); **wired to nothing** |
| **Session separation** | Each origin has its own session storage: the browser, not a naming convention, keeps the tokens apart | Follows from separate origins |
| **Token scope** | A token issued for the application plane is refused by administration routes, whatever its holder's office | An identity decision; **not started** |
| **CSP boundaries** | Origin B: same-origin connections, no framing, no inline script once a nonce is in place; Studio's policy is no longer the runtime's | Not deployed |
| **Deployment roles** | One artefact started as `studio` or as `runtime`; each role answers 404 for the other's pages | Not built |
| **Version compatibility** | The runtime states the manifest formats and Engine API versions it draws, and draws nothing else | **Built and in force:** `runtime/model.ts` `incompatibility`; the refusal is shown instead of the application; "About this application" states both versions |
| **Migration and rollback** | Each step of §4 is a configuration change; rolling back is starting the single role again | Plan only |

Regression tests that exist today: the runtime imports nothing of Studio's; it has its own token key; it asks only
its own use case's versioned API; it is opened without an opener; one address is set once; it refuses a manifest
format or Engine API it does not know (`studio/web/tests/runtime.test.ts`, `forward.test.ts`). Simulation works as
before: 108 application browser checks.

## 5. What this assessment does not claim

* It does not claim the runtime is isolated: it is not, in the browser.
* It does not claim a penetration test: none was run.
* It does not change who may do what: the Engine decides that in every option.

## 6. Decision requested (D35 d)

| # | Question | If "yes" | If no answer |
|---|---|---|---|
| a | Confirm that one origin is acceptable **for simulation only**? | Recorded; production stays blocked on steps 2 and 3 | The default stays, unconfirmed |
| b | Approve steps 2 and 3 (two roles, two origins) as the next deployment change? | Implemented with the tests of §4 | Nothing is deployed differently |
| c | Take tokens for one plane (step 6) into the identity roadmap? | Specified with IAM | Not started |
