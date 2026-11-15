# API versions and compatibility

Autology has two HTTP APIs: the **engine** API of one use case (`/api/...`, reached through the platform at
`/w/<ws>/u/<uc>/api/...`) and the **platform** API (`/platform/...`). Since 15 November 2026 both have a
version 1:

| | Engine | Platform |
|---|---|---|
| Version 1 base | `/api/v1/...` (`/w/<ws>/u/<uc>/api/v1/...`) | `/platform/v1/...` |
| Contract (OpenAPI 3.1) | `GET /api/openapi.json` | `GET /platform/openapi.json` |
| Legacy paths | `/api/...`, unchanged | `/platform/...`, unchanged |
| Copy used by Studio | `studio/web/api/engine.openapi.json` | `studio/web/api/platform.openapi.json` |

Print or rewrite the contracts with `python -m autology openapi [engine|platform]` and
`python -m autology openapi --write`. Studio's TypeScript types are generated from the committed copies
(`npm run generate:api` in `studio/web`, `openapi-typescript`); CI fails if either the copies or the generated
types differ from what the engine publishes.

## What version 1 guarantees

- **One implementation.** A v1 path and its legacy path run the same handler, with the same authentication,
  permissions, row and field rules, stage gates and audit. Versioning changes the shape of the answer, never
  what is allowed.
- **Same sign-in everywhere.** `Authorization: Bearer <token>` (or a company sign-in token), for both APIs.
- **Workspace scope.** A workspace, use case or route the caller may not open gets one identical `404`,
  whether it is someone else's, does not exist or is simply not granted, so a v1 answer reveals nothing a legacy
  answer did not.
- **One error shape.** Every v1 error is
  `{"error": {"status": 409, "code": "conflict", "message": "...", "details": {...}}}`.
  `code` is one of `invalid_request` (400), `unauthenticated` (401), `forbidden` (403), `not_found` (404),
  `method_not_allowed` (405), `conflict` (409), `length_required` (411), `payload_too_large` (413),
  `internal_error` (500), `unavailable` (502/503). `details` carries what the legacy answer had next to its
  error string (for a conflict, the current revision or record; for a refused stage move, the checks).
- **Pagination.** Lists that take `limit` and `offset` add
  `"page": {"limit", "offset", "returned", "next_offset"}`; `next_offset` is `null` on the last page. Filters
  are the existing query parameters of each route, as listed in the contract.
- **Headers.** Every answer carries `X-Autology-API-Version: 1` or `legacy`. Legacy answers also carry
  `Link: </api/v1/...>; rel="successor-version"` (or `/platform/v1/...`).

## Compatibility policy

1. **Within v1, changes are additive only**: new routes, new optional request fields, new response fields,
   new values in `details`. Clients must ignore fields they do not know (the schemas say
   `additionalProperties: true` for this reason). Removing or renaming a field, tightening a request rule,
   changing a status code or an error `code`, or changing a field's type needs a v2.
2. **Legacy paths keep their exact shape** (`{"error": "<text>"}` errors, no `page`) for existing integrations:
   the Console, the MCP relay, the generated SDKs and scripts. They are **deprecated**, not removed. Removal
   needs a release note at least one minor release in advance and is an owner decision; no date is set.
3. **A v2**, if ever needed, runs next to v1 the same way v1 runs next to the legacy paths; v1 then follows
   rule 2.
4. The contract tests (`tests/test_api_contract.py`, `tests/test_api_v1.py`) are the definition of "the
   same": every typed response is validated against its schema from a real server, errors against the
   envelope, and the published contract against the copy Studio is generated from.

## Migration

Studio uses v1 only. Other clients can move route by route: change the prefix, read errors from
`error.message` (and `error.details`), and read list continuations from `page.next_offset`. Nothing else
changes.

## Limits (15 November 2026)

- Typed response schemas exist for the routes Studio uses and the core record routes (health, me, objects,
  ontology, model draft, validation, proposals; every platform route). Other engine routes are in the contract
  with their parameters, permissions and error responses, but with a generic object as their 200 schema.
- Not every list route is paginated: only those that already took `limit`/`offset`.
- The v1 envelope is produced by the engine and the platform router. A proxy in front of them may answer
  with its own shape (for example a gateway timeout); clients should handle a non-JSON or non-envelope error.
