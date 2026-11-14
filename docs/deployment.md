# Deploying Autology (Tier 3)

## What ships

| Artifact | Where | Contents |
|---|---|---|
| Python package | `pip install autology` from the wheel on each GitHub release (`.[llm]` for the model client, `.[postgres]` for the PostgreSQL driver) | the framework, the CLI and the web inbox |
| Docker image | `ghcr.io/<owner>/<repo>:<version>` and `:latest`, built by [`release.yml`](../.github/workflows/release.yml) on every `v*` tag | Python 3.13, Autology with the model client and PostgreSQL driver, running as an unprivileged user |
| Compose example | [`deploy/docker-compose.yml`](../deploy/docker-compose.yml) | Autology with the insurance example, and Prometheus as an optional profile |

A release is cut by pushing a tag that matches the version in `pyproject.toml` (`git tag v0.4.0 && git push origin
v0.4.0`). The workflow refuses a tag that does not match, builds the wheel and source archive, builds the image,
runs the smoke test against it, pushes it, and creates the GitHub release with the files attached.

## Running the image

```bash
docker run -d --name autology -p 127.0.0.1:8800:8800 \
  -v "$PWD/my-deployment:/config:ro" -v autology-data:/data \
  --env-file autology.env \
  ghcr.io/<owner>/<repo>:0.4.0
```

- **`/config`** (read-only) holds `server.json` and every file it names: ontology, tools, pipelines, data.
- **`/data`** (a volume) holds the store, `/data/autology.db`. The image passes `--store /data/autology.db`, so the
  config's own `store` path is ignored inside the container.
- **Secrets come from the environment**, never from files in `/config`: `AUTOLOGY_AUDIT_KEY` (required: the
  server refuses to start without it), one `AUTOLOGY_TOKEN_*` per API-token user, pipeline and reporting
  connection strings (`dsn_env`), API keys for HTTP sources, `ANTHROPIC_API_KEY` if the assistant is on, and the
  OIDC client secret if the client is confidential.
- The container has a health check on `/api/health`, stops cleanly on `docker stop` (SIGTERM), and runs as user
  `autology` (uid 10001).
- Put a reverse proxy with TLS (nginx, Caddy, Traefik, a cloud load balancer) in front before exposing it. The
  inbox's sign-in with OpenID Connect requires `https` redirect URIs except on localhost.

Building behind a TLS-inspecting proxy: `docker build --secret id=extra_ca,src=/path/to/proxy-ca.crt -t autology .`
(the certificate is used for the build only, not kept in the image).

## Backups

```bash
docker exec autology autology backup /config/server.json /data/backups/2026-11-13.db --store /data/autology.db
```

`autology backup` uses SQLite's online backup, so it is consistent while the server keeps running. It writes one
self-contained file, then opens the copy and checks the schema and **every run's audit chain**; the command exits
with 2 if any chain does not verify. Copy the file off the machine (object storage, another host).

**Restore:** stop the server, replace `/data/autology.db` with the backup (and delete any `autology.db-wal` and
`autology.db-shm` next to it), start the server. The audit chains only verify with the same `AUTOLOGY_AUDIT_KEY`,
so keep that key with the backups' recovery instructions, not with the backups.

## Upgrades

1. Take a backup.
2. Start the new version on the same volume. The store's schema is upgraded in place on start-up (new tables and
   columns only; nothing is dropped). This release moves it to schema 11. Schema 11 seals every stored run record (see the audit notes in [platform.md](platform.md)). Records already in the store are sealed as they are, so check them first: the step-1 backup (`autology backup`) lists any run whose audit chain does not verify, and the `autology_audit_unverified_runs` metric must be 0.
3. Rolling back means restoring the backup: an older version refuses to open a store with a newer schema.

The ontology is versioned separately: check a new ontology with `autology diff OLD NEW` before you deploy it.

## Checked

- `deploy/smoke_test.sh` builds on the image: start, health, sign-in, a data load that triggers a governed run,
  metrics, refusal of a bad token, an online backup inside the container with every audit chain verified, a
  graceful stop, and a restart on the same volume with the data and runs intact. CI runs it on every push.
- The compose file, with the monitoring profile, started Autology and Prometheus; Prometheus scraped Autology over
  the compose network.
- The wheel installs into a clean virtual environment with the inbox's files and the `autology` command.

## Not included

Kubernetes manifests or a Helm chart, high availability (SQLite is one writer on one machine; run one replica),
automatic scheduled backups (schedule `autology backup` with cron or your platform's job runner), and signed images.
