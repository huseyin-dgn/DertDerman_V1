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


if [ ! -f "${BACKUP_DIR}/media.tar.gz" ]; then
    echo "media.tar.gz not found." >&2
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


running_services="$(
    docker compose \
        -f "${COMPOSE_FILE}" \
        --env-file "${ENV_FILE}" \
        ps \
        --status running \
        --services
)"


if printf '%s\n' "${running_services}" |
    grep -qx "web"
then
    echo "Refusing media restore while web service is running." >&2
    exit 1
fi


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


echo
echo "DANGER:"
echo "This operation replaces all media files."
echo

printf "Type RESTORE MEDIA to continue: "

read confirmation


if [ "${confirmation}" != "RESTORE MEDIA" ]; then
    echo "Media restore cancelled."
    exit 1
fi


docker run \
    --rm \
    -v "${media_volume}:/data" \
    alpine:3.22 \
    sh -c '
        find /data \
            -mindepth 1 \
            -maxdepth 1 \
            -exec rm -rf -- {} +
    '


docker run \
    --rm \
    -v "${media_volume}:/data" \
    -v "${BACKUP_DIR}:/backup:ro" \
    alpine:3.22 \
    sh -c '
        cd /data
        tar -xzf /backup/media.tar.gz
    '


echo
echo "Media restore completed."
