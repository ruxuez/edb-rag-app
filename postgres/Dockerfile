# Postgres 18 + aidb + pgfs, built on top of EDB's own CloudNativePG operand
# image. That base image ships bare Postgres binaries with no standalone
# entrypoint (it's designed to be driven by the CNPG operator's instance
# manager) and doesn't include aidb/pgfs, so both are added here: the
# extensions via EDB's package repo, and our own entrypoint below.
ARG PG_BASE_IMAGE=docker.enterprisedb.com/k8s/postgresql:18.6-standard-ubi9
FROM ${PG_BASE_IMAGE}

ARG POSTGRES_MAJOR=18
# Build-time only: used to fetch packages from EDB's repo. The repo file it
# writes (which embeds this token in its URL) is removed before this RUN
# instruction's layer is committed, so it is never persisted in the image.
ARG EDB_SUBSCRIPTION_TOKEN

USER root

RUN set -eux; \
    test -n "${EDB_SUBSCRIPTION_TOKEN}"; \
    curl -1sLf "https://downloads.enterprisedb.com/${EDB_SUBSCRIPTION_TOKEN}/enterprise/setup.rpm.sh" | bash; \
    dnf install -y "edb-pg${POSTGRES_MAJOR}-aidb" "edb-pg${POSTGRES_MAJOR}-pgfs"; \
    dnf clean all; \
    rm -rf /var/cache/dnf /etc/yum.repos.d/enterprisedb-enterprise.repo

ENV PGDATA=/var/lib/postgresql/data
RUN mkdir -p "${PGDATA}" && chown -R postgres:postgres /var/lib/postgresql

COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

USER postgres
EXPOSE 5432
ENTRYPOINT ["docker-entrypoint.sh"]
