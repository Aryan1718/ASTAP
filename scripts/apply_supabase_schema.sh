#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
MIGRATIONS_DIR="${ROOT_DIR}/migrations"

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required but was not found in PATH." >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo ".env not found at ${ENV_FILE}. Copy .env.example to .env first." >&2
  exit 1
fi

if [[ ! -d "${MIGRATIONS_DIR}" ]]; then
  echo "Migrations directory not found at ${MIGRATIONS_DIR}." >&2
  exit 1
fi

SUPABASE_DB_URL="$(
  grep -E '^SUPABASE_DB_URL=' "${ENV_FILE}" | tail -n 1 | cut -d '=' -f 2-
)"

if [[ -z "${SUPABASE_DB_URL}" ]]; then
  echo "SUPABASE_DB_URL is not set in .env." >&2
  exit 1
fi

MIGRATION_FILES=()

PRIMARY_MIGRATION="${MIGRATIONS_DIR}/001_supabase_init.sql"
if [[ -f "${PRIMARY_MIGRATION}" ]]; then
  MIGRATION_FILES+=("${PRIMARY_MIGRATION}")
fi

while IFS= read -r migration_file; do
  if [[ "${migration_file}" == "${PRIMARY_MIGRATION}" ]]; then
    continue
  fi
  if [[ "$(basename "${migration_file}")" == "001_init.sql" ]]; then
    continue
  fi
  MIGRATION_FILES+=("${migration_file}")
done < <(find "${MIGRATIONS_DIR}" -maxdepth 1 -type f -name '*.sql' | sort)

if [[ "${#MIGRATION_FILES[@]}" -eq 0 ]]; then
  echo "No SQL migrations found in ${MIGRATIONS_DIR}." >&2
  exit 1
fi

for migration_file in "${MIGRATION_FILES[@]}"; do
  echo "Applying ${migration_file} to Supabase..."
  psql "${SUPABASE_DB_URL}" -v ON_ERROR_STOP=1 -f "${migration_file}"
done

echo "All Supabase migrations applied successfully."
