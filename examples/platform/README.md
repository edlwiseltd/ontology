# Two isolated workspaces behind one router

- **acme** has two use cases with different ontologies: `claims` (motor insurance) and `orders` (order fulfilment).
- **northwind** has its own `claims` use case. It uses the same ontology as Acme's, but its data, runs, reviews,
  audit chain and Claude key are separate. Both workspaces have a member called `hana`; they are different people
  with different tokens.

```bash
export AUTOLOGY_AUDIT_KEY=...  ACME_TOKEN_ADA=... ACME_TOKEN_HANA=... ACME_TOKEN_IVAN=... ACME_TOKEN_MARIA=...
export ACME_TOKEN_OLIVIA=... ACME_TOKEN_LENA=... NORTHWIND_TOKEN_NADIA=... NORTHWIND_TOKEN_HANA=...
python -m autology platform examples/platform/platform.json --port 8700
curl -H "Authorization: Bearer $ACME_TOKEN_HANA" http://127.0.0.1:8700/platform/me
python -m autology console --engine http://127.0.0.1:8700/w/acme/u/claims --port 8900
```

Each use case keeps its data in `data/<workspace>/<use case>/autology.db`; a Claude key saved from the Console is
kept in `data/<workspace>/secrets.json`. See `docs/workspaces.md`.
