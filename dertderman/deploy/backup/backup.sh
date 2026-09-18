#!/bin/sh

set -eu

umask 077

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/dertderman}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"


case "${BACKUP_ROOT}" in
    ""|"/"|"/var"|"/var/backups")
        echo "Unsafe BACKUP_ROOT." >&2
        exit 1
        ;;
esac


case "${RETENTION_DAYS}" in
    ''|*[!0-9]*)
        echo "RETENTION_DAYS must be a non-negative integer." >&2
        exit 1
        ;;
esac


timestamp="$(date -u '+%Y%m%dT%H%M%SZ')"

backup_dir="${BACKUP_ROOT}/${timestamp}"

mkdir -p "${backup_dir}"


echo "Creating PostgreSQL backup..."


docker compose \
    -f "${COMPOSE_FILE}" \
    --env-file "${ENV_FILE}" \
    --profile tools \
    run \
    --rm \
    --no-deps \
    -T \
    db-tools \
    pg_dump \
        --format=custom \
        --no-owner \
        --no-acl \
    > "${backup_dir}/postgres.dump"


if [ ! -s "${backup_dir}/postgres.dump" ]; then
    echo "PostgreSQL backup is empty." >&2
    exit 1
fi


echo "Creating media backup..."


project_name="$(
    docker compose \
        -f "${COMPOSE_FILE}" \
        --env-file "${ENV_FILE}" \
        config |
        awk '/^name:/ {print $2; exit}'
)"


if [ -z "${project_name}" ]; then
    echo "Compose project name could not be determined." >&2
    exit 1
fi


media_volume="${project_name}_media_data"


if ! docker volume inspect \
    "${media_volume}" \
    >/dev/null 2>&1
then
    echo "Media volume does not exist: ${media_volume}" >&2
    exit 1
fi


docker run \
    --rm \
    -v "${media_volume}:/data:ro" \
    -v "${backup_dir}:/backup" \
    alpine:3.22 \
    sh -c '
        cd /data
        tar -czf /backup/media.tar.gz .
    '


if [ ! -s "${backup_dir}/media.tar.gz" ]; then
    echo "Media backup is empty." >&2
    exit 1
fi


echo "Generating SHA256 checksums..."


(
    cd "${backup_dir}"

    sha256sum \
        postgres.dump \
        media.tar.gz \
        > SHA256SUMS
)


echo "Verifying checksums..."


(
    cd "${backup_dir}"

    sha256sum -c SHA256SUMS
)


echo "Applying retention policy..."


find "${BACKUP_ROOT}" \
    -mindepth 1 \
    -maxdepth 1 \
    -type d \
    -mtime "+${RETENTION_DAYS}" \
    -exec rm -rf -- {} +


echo
echo "Backup completed:"
echo "${backup_dir}"
