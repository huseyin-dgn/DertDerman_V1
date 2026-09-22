#!/bin/sh

set -eu

umask 077


if [ "$#" -ne 1 ]; then
    echo "Usage: $0 /path/to/backup-directory" >&2
    exit 2
fi


BACKUP_DIR="$1"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"


if [ ! -f "${BACKUP_DIR}/postgres.dump" ]; then
    echo "postgres.dump not found." >&2
    exit 1
fi


if [ ! -f "${BACKUP_DIR}/SHA256SUMS" ]; then
    echo "SHA256SUMS not found." >&2
    exit 1
fi


echo "Verifying backup integrity..."


(
    cd "${BACKUP_DIR}"

    sha256sum -c SHA256SUMS
)


echo
echo "Backup integrity verified."
echo
echo "DANGER:"
echo "This operation replaces PostgreSQL application data."
echo "Database-writing application services must be stopped."
echo


running_services="$(
    docker compose \
        -f "${COMPOSE_FILE}" \
        --env-file "${ENV_FILE}" \
        ps \
        --status running \
        --services
)"


if printf '%s\n' "${running_services}" |
    grep -Eq '^(web|email-worker|migrate|db-bootstrap)$'
then
    echo "Refusing restore while a database-writing application service is running." >&2
    exit 1
fi


printf "Type RESTORE to continue: "

read confirmation


if [ "${confirmation}" != "RESTORE" ]; then
    echo "Restore cancelled."
    exit 1
fi


cat "${BACKUP_DIR}/postgres.dump" |
docker compose \
    -f "${COMPOSE_FILE}" \
    --env-file "${ENV_FILE}" \
    --profile tools \
    run \
    --rm \
    --no-deps \
    -T \
    db-tools \
    pg-restore-current \
        --clean \
        --if-exists \
        --no-owner \
        --no-acl \
        --exit-on-error


echo
echo "PostgreSQL restore completed."
