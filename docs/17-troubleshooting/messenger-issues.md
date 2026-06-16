# Messenger Issues

---

## Webhook Returns 403

**Check 1: HMAC verification**
```bash
journalctl -u nexus-chat | grep "signature_mismatch" | tail -5
```
If present: `MESSENGER_APP_SECRET` is wrong or stale.

Fix:
1. Regenerate App Secret in Meta Dashboard → App Settings → Basic
2. Update `MESSENGER_APP_SECRET` in `/home/nexus-rag/.env`
3. `sudo systemctl restart nexus-chat`

**Check 2: Verify token mismatch**

Only affects `GET /webhook/messenger` (initial verification, not ongoing events). Compare `MESSENGER_VERIFY_TOKEN` in `.env` against what's set in Meta App Dashboard → Webhooks.

---

## Bot Not Replying

Work through this checklist in order:

```bash
# 1. Is the page bound to a tenant?
curl https://chat.nexus.gayo-sphere.cloud/api/integrations/messenger/pages \
  -H "Authorization: Bearer $TOKEN"

# 2. Is the sender queue backed up?
redis-cli LLEN queue:{sender_psid}

# 3. Is there an inflight lock stuck?
redis-cli TTL inflight:{sender_psid}

# 4. Is the bot in HITL pause?
redis-cli EXISTS hitl:{sender_psid}

# 5. Check recent errors
journalctl -u nexus-chat | grep "{sender_psid}" | tail -20
```

| Cause | Fix |
|---|---|
| Page not bound | `POST /api/integrations/messenger/pages` |
| Inflight key stuck (crashed pipeline) | Wait 120s TTL or `redis-cli DEL inflight:{psid}` |
| HITL pause active | `POST /api/integrations/messenger/hitl/resume` with `sender_id` |
| App in Development mode | Only admin/testers can interact; submit for App Review |
| 24h messaging window expired | Cannot reply; wait for user to send next message |

---

## HITL Stuck (Not Resuming)

```bash
# Check pause key TTL
redis-cli TTL hitl:{sender_psid}
# -2 = key doesn't exist (already expired or never set)
# -1 = no TTL (shouldn't happen)
# >0 = seconds remaining

# Manual resume
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/integrations/messenger/hitl/resume \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"sender_id": "{psid}"}'
```

---

## Retry Queue Exhaustion

```bash
# Check dead-letter queue
redis-cli KEYS "dlq:messenger:*"
redis-cli HGETALL "dlq:messenger:{entry_id}"
```

Common causes:
- `MESSENGER_PAGE_TOKEN` expired → regenerate in Meta Dashboard
- 24h window expired → not recoverable; log only
- Meta Graph API 500 → transient; check Meta status page

---

## Duplicate Replies

Bot sending same response twice:

| Cause | Fix |
|---|---|
| Two webhook deliveries (Meta retries) | Ensure webhook returns `200` within 5s; check response latency |
| `inflight` key not set before processing | Bug in queue consumer — check `messenger/queue.py` |
| Coalesce window not working | Check `coalesce:{psid}` key in Redis during rapid messages |

---

## Comment Triage Not Firing

```bash
# Check feed subscription
# → Meta App Dashboard → Webhooks → verify "feed" is subscribed
```

| Cause | Fix |
|---|---|
| `feed` event not subscribed | Re-subscribe in Meta Dashboard |
| Page not bound to tenant | Bind page first |
| Comment older than 7 days | Private reply not possible; expected |

---

## Related Docs

- [Inbound Message Flow](../07-messenger-integration/inbound-message-flow.md)
- [HITL Handover](../07-messenger-integration/hitl-handover.md)
- [Security & PII](../07-messenger-integration/security-pii.md)
- [Rate Limits & Coalescing](../07-messenger-integration/rate-limits-coalescing.md)
