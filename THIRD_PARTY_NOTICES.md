# Third-party notices

Autology itself is proprietary (see [LICENSE](LICENSE)). The engine core has **no runtime dependencies**: it uses
the Python standard library only. Optional extras, the Docker image and CI install the components below, each
under its own licence. The machine-readable inventory is [`deploy/third_party_licences.json`](deploy/third_party_licences.json);
`tests/test_leg1_licences.py` checks, in CI, that every installed dependency of a declared component is listed
there with the licence its own metadata states, and that none is under a licence the policy does not allow.

**Policy.** Autology is distributed under a proprietary licence (owner decision D5, subject to intellectual-property and third-party licence review). Permissive licences are allowed; LGPL (weak copyleft) only as an optional, unmodified, dynamically imported dependency and after legal review; GPL/AGPL are not allowed.

| Component | Licence | Used for | Shipped in | Review |
|---|---|---|---|---|
| absl-py | Apache-2.0 | CI only: dependency of ortools | no |  |
| annotated-types | MIT | dependency of anthropic (pydantic) | Docker image |  |
| anthropic | Apache-2.0 | optional extra 'llm': the Claude model client (assistant, model reasoners) | Docker image |  |
| anyio | MIT | dependency of anthropic | Docker image |  |
| backports-zoneinfo | Apache-2.0 | dependency of psycopg on old Pythons | no |  |
| build | MIT | CI and release: wheel build | no |  |
| certifi | MPL-2.0 | dependency of anthropic (httpx): CA bundle | Docker image | MPL-2.0 file-level copyleft; used unmodified |
| cffi | MIT-0 | CI only: dependency of cryptography | no |  |
| colorama | BSD-3-Clause | CI and release: dependency of build | no |  |
| coverage | Apache-2.0 | CI only: coverage gate | no |  |
| cryptography | Apache-2.0 OR BSD-3-Clause | CI only: interoperability test of the built-in RSA signature check | no |  |
| distro | Apache-2.0 | dependency of anthropic | Docker image |  |
| docstring-parser | MIT | dependency of anthropic | Docker image |  |
| et-xmlfile | MIT | dependency of openpyxl | not yet |  |
| exceptiongroup | MIT | dependency of anyio on Python < 3.11 | Docker image (older Pythons) |  |
| h11 | MIT | dependency of anthropic (httpx) | Docker image |  |
| httpcore | BSD-3-Clause | dependency of anthropic (httpx) | Docker image |  |
| httpcore2 | BSD-3-Clause | dependency of anthropic (some versions) | Docker image |  |
| httpx | BSD-3-Clause | dependency of anthropic | Docker image |  |
| httpx2 | BSD-3-Clause | dependency of anthropic (some versions) | Docker image |  |
| idna | BSD-3-Clause | dependency of anthropic (httpx) | Docker image |  |
| immutabledict | MIT | CI only: dependency of ortools | no |  |
| importlib-metadata | Apache-2.0 | CI only: dependency of opentelemetry-api on some versions | no |  |
| isodate | BSD-3-Clause | CI only: dependency of rdflib on some versions | no |  |
| jiter | MIT | dependency of anthropic | Docker image |  |
| numpy | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | CI only: dependency of ortools | no |  |
| openpyxl | MIT | approved for the Excel template factory (XL-1, R2); not used yet | not yet |  |
| opentelemetry-api | Apache-2.0 | CI only: dependency of ortools | no |  |
| ortools | Apache-2.0 | CI only: the scheduling example's CP-SAT solver tests | no |  |
| packaging | Apache-2.0 OR BSD-2-Clause | CI and release: dependency of build | no |  |
| pandas | BSD-3-Clause | CI only: dependency of ortools | no |  |
| protobuf | BSD-3-Clause | CI only: dependency of ortools | no |  |
| psycopg | LGPL-3.0-only | optional extra 'postgres': SQL pipelines and the reporting database | Docker image | LGPL obligations for a bundled, unmodified library: keep its licence text in the image and allow it to be replaced. Confirm with counsel before distributing the image |
| psycopg-binary | LGPL-3.0-only | binary build of psycopg (bundles libpq, PostgreSQL licence) | Docker image | as psycopg; libpq is under the PostgreSQL licence (permissive) |
| pycparser | BSD-3-Clause | CI only: dependency of cffi | no |  |
| pydantic | MIT | dependency of anthropic | Docker image |  |
| pydantic-core | MIT | dependency of anthropic | Docker image |  |
| pyparsing | MIT | CI only: dependency of rdflib | no |  |
| pyproject-hooks | MIT | CI and release: dependency of build | no |  |
| python-dateutil | Apache-2.0 AND BSD-3-Clause | CI only: dependency of pandas | no |  |
| pytz | MIT | CI only: dependency of pandas on some versions | no |  |
| pyyaml | MIT | optional extra 'yaml': YAML ontologies | not in the image |  |
| rdflib | BSD-3-Clause | CI only: RDF/OWL export tests | no |  |
| setuptools | MIT | build backend | no |  |
| six | MIT | CI only: dependency of python-dateutil | no |  |
| sniffio | MIT OR Apache-2.0 | dependency of anthropic | Docker image |  |
| tomli | MIT | CI and release on Python 3.10: dependency of build | no |  |
| truststore | MIT | dependency of anthropic (some versions) | Docker image |  |
| typing-extensions | PSF-2.0 | dependency of anthropic, psycopg | Docker image |  |
| typing-inspection | MIT | dependency of anthropic (pydantic) | Docker image |  |
| tzdata | Apache-2.0 | dependency of psycopg on some platforms | Docker image |  |
| zipp | MIT | CI only: dependency of importlib-metadata | no |  |

**Not Python packages.**

- **python:3.13-slim (Docker base image)**: Debian packages under their own licences and CPython under the PSF licence; review the image's /usr/share/doc/*/copyright before distributing it
- **Console and inbox (autology/static, autology/console_static)**: own code, no third-party JavaScript or CSS

**Open for the legal review:** the LGPL-3.0 PostgreSQL driver bundled in the Docker image, MPL-2.0 `certifi`, the
Debian packages of the base image, and the final licence text and legal entity in `LICENSE`.
