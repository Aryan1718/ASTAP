#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATION_FILE="${ROOT_DIR}/migrations/001_init.sql"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required but was not found in PATH." >&2
  exit 1
fi

if [[ ! -f "${MIGRATION_FILE}" ]]; then
  echo "Migration file not found at ${MIGRATION_FILE}." >&2
  exit 1
fi

echo "Applying ${MIGRATION_FILE} to local Postgres container..."
docker compose exec -T db psql -U astsp -d astsp -v ON_ERROR_STOP=1 -f - < "${MIGRATION_FILE}"
echo "Schema applied successfully."
