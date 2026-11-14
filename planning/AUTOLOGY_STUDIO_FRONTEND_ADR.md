# ADR — Autology Studio frontend: Next.js, boundaries, libraries

*14 November 2026 · Status: **Accepted** (owner decision D9: Next.js + React + TypeScript). Statuses below:
Verified / Implemented but unverified / Demo-only / Planned / Blocked.*

## Context

Studio is the design workbench (administrators, solution architects, domain experts, reviewers). The engine owns
the model, rules, permissions, approvals, audit, execution gates and (when built) releases. Until 14 November a
small interim shell (Python standard library + plain JavaScript) served the R2 slice; the owner chose Next.js for
the product Studio.

## Decision

1. **Separate application** in `studio/web`: its own `package.json`, exact pinned versions, lock file, build, tests
   and CI job (`studio`). Not part of the engine's Python package. The engine runs headless without it (shown in
   CI by stopping Studio and calling the engine).
2. **One narrow server-side component**: `lib/forward.ts`, used by two route handlers (`/platform/*`, `/w/*`). It
   forwards GET and POST only, `Authorization` and `Content-Type` only, never follows redirects, bounds bodies
   (1 MB) and returns 502 when the platform is down. It holds no policy: no Server Actions, no business logic, no
   database, no secret. Everything else is client components.
3. **Session**: the member's bearer token stays in the browser tab (`sessionStorage`, never `localStorage`), sent
   on each request. No cookie → no CSRF surface. A cookie-based BFF session is a later option (needs CSRF defence
   and an identity-provider decision).
4. **API contract**: the engine's OpenAPI 3.1 contract (`GET /api/openapi.json`, API-1) is authoritative for
   engine routes. The platform's own routes (`/platform/...`) are not yet in a published contract; Studio's typed
   client (`lib/api.ts`, `lib/types.ts`) is hand-written against them until they are (gap recorded in the
   [API matrix](AUTOLOGY_STUDIO_API_CONTRACT_MATRIX.md)). A generated client follows when bodies are typed.
5. **One model, many views**: the canvas and the entity list are projections of the engine's ontology summary
   (`lib/graph.ts`); node positions are presentation only.
6. **Security headers** on every page: CSP (`default-src 'self'`, `connect-src 'self'`, `frame-ancestors 'none'`,
   `object-src 'none'`, `base-uri 'none'`), `X-Frame-Options: DENY`, `nosniff`, `no-referrer`. Known weakness:
   `script-src` and `style-src` include `'unsafe-inline'` (Next.js hydration, React Flow inline styles); a
   nonce-based policy is planned.

## Libraries

| Package | Version | Licence | Use | Status |
|---|---|---|---|---|
| next | 16.4.6 | MIT | App Router, build, relay route handlers | Verified (builds, e2e) |
| react, react-dom | 19.3.1 | MIT | UI | Verified |
| @xyflow/react (React Flow) | 12.12.1 | MIT | Ontology canvas (read-only today) | Verified |
| typescript | 5.9.3 | Apache-2.0 | Types (dev) | Verified |
| vitest | 5.1.0 | MIT | Unit tests (dev) | Verified |
| playwright | 1.63.0 | Apache-2.0 | Browser tests (dev) | Verified |
| elkjs | — | **EPL-2.0 OR GPL-3.0-or-later** | Auto-layout (recommended by the spec) | **Planned, licence review first**: a weak-copyleft dependency for commercial bundling; a built-in layered layout is used meanwhile |
| Tailwind CSS, shadcn/ui, Radix | — | MIT | Design system | Planned: today a small token-based stylesheet (light/dark) covers the shell; adopt when forms, dialogs and menus grow |
| TanStack Query/Table, Zustand, dnd-kit | — | MIT | Server state, tables, editor state, drag/drop | Planned with the editing increments |
| Cytoscape.js | — | MIT | Large-graph exploration | Not adopted (only with a benchmark showing React Flow insufficient) |

Shipped npm packages and their licences: `studio/web/licences.json` (77 packages: 62 permissive; the optional
`sharp`/`libvips` binaries are LGPL-3.0 and `caniuse-lite` is CC-BY-4.0 — legal question L6, D19).

## Consequences

- Studio can be built, released and deployed on its own; the engine's suite does not depend on Node.
- Any write goes through the platform/engine API; UI permission hints are advisory and the browser tests call the
  API directly to show the server refuses (403/404).
- The ontology and its strict JSON Schema (MOD-1) remain the single source of truth; SHACL/LinkML are at most a
  separately labelled experiment (not started).
- Retired: the interim Python shell (`studio/server.py`, `studio/static`), whose functions are all covered here.
