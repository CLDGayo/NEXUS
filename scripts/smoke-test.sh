#!/usr/bin/env bash
# Phase 8 smoke test — drives the live webhook surface end-to-end.
#
# Usage:
#   bash scripts/smoke-test.sh https://messenger.nexus.gayo-sphere.cloud
#
# Requires env vars (or sourced from .env.prod):
#   WEBHOOK_API_KEY              shared secret n8n posts in X-Webhook-Api-Key
#   MESSENGER_RATE_LIMIT_PER_MIN (optional, default 20)
#
# Exits non-zero on any failure so this script is safe to wire into CI / cron.

set -euo pipefail

BASE_URL="${1:-${BASE_URL:-http://127.0.0.1:8000}}"
API_KEY="${WEBHOOK_API_KEY:-}"
RATE_LIMIT="${MESSENGER_RATE_LIMIT_PER_MIN:-20}"
ENDPOINT="${BASE_URL%/}/webhook/messenger/inbound"
TS="$(date +%s)"
USER_PREFIX="smoke-$$-${TS}"

if [[ -z "${API_KEY}" ]]; then
  echo "FATAL: WEBHOOK_API_KEY env var is empty." >&2
  exit 2
fi

pass() { printf "  \033[32mOK\033[0m   %s\n" "$1"; }
fail() { printf "  \033[31mFAIL\033[0m %s\n" "$1"; exit 1; }
info() { printf "  ..   %s\n" "$1"; }

# Returns: "<http_status>|<body>"
post_inbound() {
  local user_id="$1" text="$2" corr="$3"
  local body
  body=$(cat <<JSON
{"user_id":"${user_id}","message_text":"${text}","timestamp":${TS},"channel":"messenger","correlation_id":"${corr}"}
JSON
)
  local resp
  resp=$(curl -sS -o /tmp/smoke_body.$$ -w "%{http_code}" \
              -X POST "${ENDPOINT}" \
              -H "Content-Type: application/json" \
              -H "X-Webhook-Api-Key: ${API_KEY}" \
              --data "${body}")
  local out
  out=$(cat /tmp/smoke_body.$$)
  rm -f /tmp/smoke_body.$$
  printf "%s|%s" "${resp}" "${out}"
}

echo "=== Test 1: auth enforcement (no header) ==="
status=$(curl -sS -o /dev/null -w "%{http_code}" \
              -X POST "${ENDPOINT}" \
              -H "Content-Type: application/json" \
              --data '{"user_id":"x","message_text":"hi","timestamp":1}')
[[ "${status}" == "401" || "${status}" == "403" || "${status}" == "503" ]] \
  && pass "missing X-Webhook-Api-Key → ${status}" \
  || fail "expected 401/403/503, got ${status}"

echo "=== Test 2: PII scrub (email + credit card) ==="
# Luhn-valid test card (Visa).
pii_text="My email is test@example.com and my card is 4111111111111111"
result=$(post_inbound "${USER_PREFIX}-pii" "${pii_text}" "${USER_PREFIX}-pii-1")
http="${result%%|*}"
body="${result#*|}"
[[ "${http}" == "200" ]] || fail "PII POST returned ${http}: ${body}"
pass "PII POST returned 200 — verify Langfuse trace shows [EMAIL_REDACTED] / [CARD_REDACTED]"
info "trace check: open Langfuse → filter correlation_id=${USER_PREFIX}-pii-1"

echo "=== Test 3: idempotency (replay same correlation_id) ==="
result=$(post_inbound "${USER_PREFIX}-idem" "first send" "${USER_PREFIX}-idem-1")
http1="${result%%|*}"; body1="${result#*|}"
result=$(post_inbound "${USER_PREFIX}-idem" "first send" "${USER_PREFIX}-idem-1")
http2="${result%%|*}"; body2="${result#*|}"
[[ "${http1}" == "200" ]] || fail "first idempotency POST returned ${http1}"
[[ "${http2}" == "200" ]] || fail "replay POST returned ${http2}"
echo "${body2}" | grep -q '"status":"duplicate"' \
  && pass "replay returned status=duplicate" \
  || fail "replay body missing status=duplicate: ${body2}"

echo "=== Test 4: rate limit (burst > ${RATE_LIMIT}/min) ==="
burst_user="${USER_PREFIX}-rl"
hits_429=0
total=$((RATE_LIMIT + 5))
for i in $(seq 1 ${total}); do
  result=$(post_inbound "${burst_user}" "burst ${i}" "${burst_user}-${i}" || true)
  http="${result%%|*}"
  [[ "${http}" == "429" ]] && hits_429=$((hits_429 + 1))
done
[[ ${hits_429} -ge 1 ]] \
  && pass "burst triggered ${hits_429}× 429 (expected ≥1 over ${total} requests)" \
  || fail "no 429s seen across ${total} rapid requests — rate-limit not enforcing"

echo
echo "All smoke tests passed."
echo "Next: verify Langfuse + n8n executions tab, then send a real Messenger DM."
