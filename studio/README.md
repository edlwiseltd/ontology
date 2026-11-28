# Autology Studio

The design workbench for workspace administrators and solution architects: a **separate Next.js application**
(`studio/web`, Next.js App Router + React + TypeScript, owner decision D9) that reaches Autology only through the
platform's HTTP API. It never imports the engine, holds no database connection and no secret; every permission,
check, stage rule and workspace boundary is the platform's and the engine's.

```bash
python -m autology platform examples/platform/platform.json --port 8700     # the platform (engine)
cd studio/web && npm ci && npm run build
AUTOLOGY_PLATFORM_URL=http://127.0.0.1:8700 npm start                       # Studio on :8960
```

| Command (in `studio/web`) | What it does |
|---|---|
| `npm run typecheck` / `npm test` | TypeScript check; unit tests (relay confinement, model projection, client, separation) |
| `npm run build` | Production build |
| `npm run generate:api` | Regenerate `lib/generated/*.ts` from the API v1 contracts in `api/` (first `python -m autology openapi --write` at the repository root); CI fails if either is stale |
| `e2e/run.sh` | Browser tests (Playwright) against a real example platform, desktop and mobile, then stops Studio and shows the engine still answers |

Licences of the npm packages Studio ships: `studio/web/licences.json` (see the legal package, D19).
Design and plans: `planning/AUTOLOGY_STUDIO_*.md`. The earlier interim Python shell was retired on 14 November
2026 once every one of its functions was covered by this application and its browser tests.
