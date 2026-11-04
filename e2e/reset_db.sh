#!/usr/bin/env bash
# Recreate the local ConnectSphere database from schema.sql and reseed it, so
# the Playwright suite starts from known data. DESTROYS the local database.
#
# Usage: bash e2e/reset_db.sh            (uses the README's default credentials)
#   DB_USER / DB_PASS / DB_NAME / DB_HOST override them.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB_USER="${DB_USER:-connectsphere_user}"
DB_PASS="${DB_PASS:-password}"
DB_NAME="${DB_NAME:-connectsphere}"
DB_HOST="${DB_HOST:-127.0.0.1}"
MYSQL=(mysql -h "$DB_HOST" -u "$DB_USER" "-p$DB_PASS")
"${MYSQL[@]}" -e "DROP DATABASE IF EXISTS \`$DB_NAME\`; CREATE DATABASE \`$DB_NAME\` CHARACTER SET utf8mb4;" 2>/dev/null
"${MYSQL[@]}" "$DB_NAME" < "$ROOT/database/schema.sql" 2>/dev/null
(cd "$ROOT/backend" && python3 scripts/seed_users.py > /dev/null 2>&1)
echo "Database $DB_NAME reset and seeded."
