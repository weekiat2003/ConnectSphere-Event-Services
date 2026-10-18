#!/usr/bin/env bash
# Smoke test for a running ConnectSphere backend.
#
# Usage: bash smoke.sh <base-url>        e.g. bash smoke.sh http://localhost:5000
#
# A handful of fast checks that the running release is alive and roughly
# right. It is not a test suite and should never take long. It expects the
# database to hold the seeded test users (backend/scripts/seed_users.py).
set -euo pipefail

BASE="${1%/}"
EMAIL="${SMOKE_EMAIL:-organiser@example.com}"
PASSWORD="${SMOKE_PASSWORD:-Password123!}"

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

# 1. Wait up to 30 seconds for the app to answer.
for i in $(seq 1 30); do
  curl -fs "$BASE/api/health" > /dev/null 2>&1 && break
  [ "$i" = 30 ] && fail "no answer from $BASE/api/health"
  sleep 1
done

# 2. Health: the app is up AND can reach its database.
curl -fsS "$BASE/api/health" | jq -e '.status == "ok" and .database == "ok"' > /dev/null \
  || fail "/api/health did not report status=ok, database=ok"
echo "ok  health check"

# 3. A wrong password is refused with 401 (not a crash, not a success).
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\": \"$EMAIL\", \"password\": \"definitely-wrong\"}")
[ "$code" = 401 ] || fail "wrong password returned $code, expected 401"
echo "ok  wrong password is rejected"

# 4. The seeded user can log in and receives an access token.
TOKEN=$(curl -fsS -X POST "$BASE/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\": \"$EMAIL\", \"password\": \"$PASSWORD\"}" | jq -er '.accessToken') \
  || fail "login as $EMAIL failed or returned no accessToken"
echo "ok  login returns an access token"

# 5. Protected endpoints refuse anonymous callers ...
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/auth/me")
[ "$code" = 401 ] || fail "/api/auth/me without a token returned $code, expected 401"
echo "ok  protected endpoint rejects anonymous request"

# 6. ... and accept the token, returning the right user.
curl -fsS "$BASE/api/auth/me" -H "Authorization: Bearer $TOKEN" \
  | jq -e --arg e "$EMAIL" '.email == $e' > /dev/null \
  || fail "/api/auth/me did not return $EMAIL"
echo "ok  token identifies the logged-in user"

# 7. A database-backed read works: the organiser's seeded events come back.
curl -fsS "$BASE/api/events/mine" -H "Authorization: Bearer $TOKEN" \
  | jq -e 'type == "array" and length > 0' > /dev/null \
  || fail "/api/events/mine returned no events for $EMAIL"
echo "ok  organiser's events are readable"

echo "Smoke tests passed against $BASE"
