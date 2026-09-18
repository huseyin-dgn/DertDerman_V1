#!/bin/sh

set -eu

if [ ! -r "${POSTGRES_MIGRATOR_PASSWORD_FILE}" ]; then
    echo "Migrator password secret is not readable." >&2
    exit 1
fi

PGPASSWORD="$(
    tr -d '\r\n' \
        < "${POSTGRES_MIGRATOR_PASSWORD_FILE}"
)"

if [ -z "${PGPASSWORD}" ]; then
    echo "Migrator password secret is empty." >&2
    exit 1
fi

export PGPASSWORD


if [ "${1:-}" = "pg-restore-current" ]; then
    shift

    exec pg_restore \
        --dbname="${PGDATABASE}" \
        "$@"
fi


exec "$@"
