# Chat Interface

The chat page (`/chat`) is the primary user-facing surface. It streams responses via SSE, supports file uploads, and renders citations with source popups.

---

## SSE Streaming

The frontend connects to `POST /api/chat/stream` and processes the SSE event stream:

```javascript
const response = await fetch('/api/chat/stream', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ message, conversation_id, tenant_id })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const lines = decoder.decode(value).split('\n');
  for (const line of lines) {
    if (!line.startsWith('data: ')) continue;
    const event = JSON.parse(line.slice(6));
    handleEvent(event);
  }
}
```

### Event Handling

| Event type | UI action |
|---|---|
| `status` | Show "Thinking…" / "Retrieving…" status badge |
| `sources` | Render source cards in the sources panel |
| `token` | Append token to message bubble (streaming effect) |
| `follow_ups` | Render follow-up suggestion chips below message |
| `done` | Hide typing indicator; mark message complete |
| `error` | Show error toast; allow retry |

---

## Message Bubble Rendering

Messages render Markdown with these extensions:

| Feature | Rendering |
|---|---|
| `[1]`, `[2]` inline citations | Superscript links → open source popup on click |
| Code blocks | Syntax-highlighted via `highlight.js` |
| Tables | Styled with Tailwind table classes |
| Bold / italic | Standard Markdown |

---

## Source Citations Popup

Clicking a `[n]` citation opens a side panel with:
- Source document title + heading path
- Excerpt of the relevant chunk
- Link to the full document in the vault (Quartz site)
- Similarity score badge

---

## File Upload

```http
POST /api/chat/upload
Content-Type: multipart/form-data
```

Supported types: PDF, Markdown, plain text (up to 50 MB).

UI behavior:
1. User drags file onto chat input or clicks paperclip icon
2. File uploads immediately (progress bar)
3. Server ingests the file into the tenant's Qdrant collection
4. File name appears as a context chip above the message input
5. Next user message includes the uploaded document in retrieval

---

## Conversation Sidebar

Left panel lists conversations grouped by date:
- Today / Yesterday / This week / Older
- Click to load conversation history (fetched from `GET /api/conversations/{id}/messages`)
- Hover to reveal rename / delete actions

New conversation: click `+` button or `Cmd+N`.

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Enter` | Send message |
| `Shift+Enter` | New line in input |
| `Cmd+K` | Open command palette |
| `Cmd+N` | New conversation |
| `Esc` | Close source popup / command palette |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Stream hangs after "Thinking…" | SSE connection dropped | Check nginx `proxy_buffering off` for `/api/chat/stream` |
| Citations show `[?]` | Source not in `sources` event | Re-check `reranked_chunks` → `sources` mapping in orchestrator |
| File upload fails with `413` | File exceeds nginx `client_max_body_size` | Increase limit in nginx config |
| Follow-up chips not appearing | `follow_up_node` disabled | Enable toggle in workspace AI settings |

---

## Related Docs

- [Stage 5 — Generation](../02-rag-pipeline/stage-5-generation.md) — SSE event order
- [nginx Configuration](../12-deployment/nginx-configuration.md) — SSE buffering config
- [API Reference — Chat Stream](../03-api-reference/chat/stream.md)
