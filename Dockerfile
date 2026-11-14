# syntax=docker/dockerfile:1
# Autology: the governed ontology-and-agent server.
#   docker build -t autology .
#   docker run -p 8800:8800 -v "$PWD/config:/config:ro" -v autology-data:/data \
#     -e AUTOLOGY_AUDIT_KEY=... -e AUTOLOGY_TOKEN_ADMIN=... autology
FROM python:3.13-slim
# Which optional extras the image installs. The default is unchanged; "llm" builds an image without the LGPL
# PostgreSQL driver (no SQL pipelines or PostgreSQL reporting target); "" installs the engine alone. See
# planning/AUTOLOGY_PARTIAL_GAPS_CLARIFICATION.md (GAP-031) before distributing any image.
ARG EXTRAS=llm,postgres

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/doc/autology/
COPY pyproject.toml README.md ./
COPY autology ./autology
COPY deploy/image-constraints.txt ./constraints.txt
# the model client (the assistant and model reasoners) and the PostgreSQL driver (sql pipelines, reporting).
# Behind a TLS-inspecting proxy, pass its CA as a build secret (it is not kept in the image):
#   docker build --secret id=extra_ca,src=/path/to/proxy-ca.crt -t autology .
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install -c constraints.txt "$( [ -n "$EXTRAS" ] && echo ".[$EXTRAS]" || echo . )" && rm -rf /src

RUN useradd --system --uid 10001 --home-dir /data --shell /usr/sbin/nologin autology \
    && mkdir -p /data /config && chown autology /data
USER autology
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8800

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8800/api/health', timeout=4).status == 200 else 1)"

# /config holds server.json and the files it names (ontology, tools, pipelines); /data holds the store
ENTRYPOINT ["autology"]
CMD ["serve", "/config/server.json", "--host", "0.0.0.0", "--port", "8800", "--store", "/data/autology.db"]
