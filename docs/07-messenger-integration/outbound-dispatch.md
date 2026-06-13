# Outbound Dispatch

Handles sending replies from NEXUS to Messenger users via the Meta Graph API, including retry logic and dead-letter handling.

---

## Dispatch Paths

| Path | When Used | Description |
|---|---|---|
| Direct Graph API | Default | POST directly to `graph.facebook.com/v19.0/me/messages` |
| Broker | When `MESSENGER_USE_BROKER=true` | Route via message broker for reliability + retry |

Most deployments use the direct path. The broker path adds durability at the cost of latency.

---

## Message Types Sent

| Type | Meta API field | When |
|---|---|---|
| Text reply | `message.text` | Standard LLM response |
| Quick replies | `message.quick_replies` | Follow-up suggestions from `follow_up_node` |
| Generic template | `message.attachment.type=template` | Product carousel from `product_context_node` |
| Typing indicator | `sender_action=typing_on` | Sent before response to show "is typing…" |

---

## Typing Indicator

NEXUS sends a typing indicator before dispatching the response to improve UX:

```python
# Sent before reply
await send_action(recipient_id, "typing_on")
# ... generate response ...
await send_message(recipient_id, reply_text)
await send_action(recipient_id, "typing_off")
```

Typing indicator is fire-and-forget — failures are logged but do not block reply delivery.

---

## Graph API Call

```http
POST https://graph.facebook.com/v19.0/me/messages
Authorization: Bearer {MESSENGER_PAGE_TOKEN}
Content-Type: application/json

{
  "recipient": {"id": "{sender_psid}"},
  "message": {"text": "{reply_text}"},
  "messaging_type": "RESPONSE"
}
```

`messaging_type: RESPONSE` is used for replies within the 24-hour window. Outside the window, NEXUS cannot initiate proactive messages without a `MESSAGE_TAG`.

---

## Retry Queue

Failed sends are pushed to `retry:{sender_id}` in Redis with exponential backoff:

| Attempt | Delay |
|---|---|
| 1 | 5 seconds |
| 2 | 30 seconds |
| 3 | 120 seconds |

After 3 failed attempts, the message is moved to the dead-letter queue (`dlq:messenger`) and an error is logged. No further retry occurs.

---

## Dead-Letter Queue

Messages in `dlq:messenger` are Redis hashes with:

```json
{
  "sender_id": "psid",
  "tenant_id": "acme-corp",
  "reply_text": "...",
  "error": "Graph API 500",
  "failed_at": "2026-06-13T12:00:00Z",
  "attempts": 3
}
```

Dead-letter entries expire after 7 days. Inspect via:

```bash
redis-cli KEYS "dlq:messenger:*"
redis-cli HGETALL "dlq:messenger:{entry_id}"
```

---

## 24-Hour Window

Meta enforces a 24-hour messaging window — NEXUS can only reply within 24 hours of the last user message.

| Scenario | Behavior |
|---|---|
| Reply within 24h | Normal dispatch |
| Reply after 24h | Graph API returns error `(#10)`; logged as `messaging_window_expired`; not retried |
| Proactive message | Requires `MESSAGE_TAG` (not implemented — reserved for future) |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Messages in dead-letter queue | Persistent Graph API failures | Check `MESSENGER_PAGE_TOKEN` validity; regenerate if expired |
| `(#10) Application does not have permission` | 24h window expired | Cannot reply; window resets when user sends next message |
| Typing indicator not showing | Webhook event ordering | Non-blocking; ignore if bot replies correctly |
| Reply sent but user didn't receive | Messenger delivery lag | Normal; check `message_deliveries` webhook events |

---

## Related Docs

- [Inbound Message Flow](inbound-message-flow.md)
- [Rate Limits & Coalescing](rate-limits-coalescing.md)
- [Meta Webhook Setup](meta-webhook-setup.md)
