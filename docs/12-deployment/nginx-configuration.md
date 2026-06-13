# nginx Configuration

nginx reverse-proxies all inbound traffic to the correct backend. CloudPanel manages SSL certificates via Let's Encrypt.

---

## Virtual Hosts Overview

| Domain | Backend | Notes |
|---|---|---|
| `chat.nexus.gayo-sphere.cloud` | `127.0.0.1:8501` (uvicorn) | RAG chat app + API + webhook |
| `nexus.gayo-sphere.cloud` | Static files | Quartz vault site |
| `qdrant.nexus.gayo-sphere.cloud` | `127.0.0.1:6333` (Docker) | Qdrant HTTPS (Mac dev access) |
| `assets.nexus.gayo-sphere.cloud` | `127.0.0.1:9000` (MinIO) | Public object storage CDN |

---

## RAG Application Config

```nginx
# /etc/nginx/sites-available/chat.nexus.gayo-sphere.cloud

upstream nexus_chat {
    server 127.0.0.1:8501;
    keepalive 32;
}

server {
    listen 80;
    server_name chat.nexus.gayo-sphere.cloud;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name chat.nexus.gayo-sphere.cloud;

    ssl_certificate     /etc/letsencrypt/live/chat.nexus.gayo-sphere.cloud/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/chat.nexus.gayo-sphere.cloud/privkey.pem;

    # SSE streaming — disable buffering
    location /api/chat/stream {
        proxy_pass         http://nexus_chat;
        proxy_http_version 1.1;
        proxy_set_header   Connection "";
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 300s;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    # Messenger webhook — preserve raw body for HMAC verification
    location /webhook/messenger {
        proxy_pass         http://nexus_chat;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_request_buffering off;  # Pass raw body unchanged
    }

    # All other routes
    location / {
        proxy_pass         http://nexus_chat;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        client_max_body_size 50M;
    }
}
```

> **⚠️ WARNING:** `proxy_buffering off` on the SSE endpoint is critical. Without it, nginx buffers the stream and the frontend never receives tokens until the full response completes.

> **⚠️ WARNING:** `proxy_request_buffering off` on the Messenger webhook endpoint is required. If nginx buffers the request body, FastAPI reads a different byte sequence than what Meta signed — HMAC verification fails with `403`.

---

## Quartz Static Site Config

```nginx
server {
    listen 443 ssl http2;
    server_name nexus.gayo-sphere.cloud;

    ssl_certificate     /etc/letsencrypt/live/nexus.gayo-sphere.cloud/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/nexus.gayo-sphere.cloud/privkey.pem;

    root /var/www/nexus.gayo-sphere.cloud/public;
    index index.html;

    location / {
        try_files $uri $uri/ $uri.html =404;
    }

    # Cache static assets
    location ~* \.(js|css|png|jpg|webp|woff2|ico)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

---

## Reload nginx

After editing config:

```bash
sudo nginx -t          # Test config syntax
sudo systemctl reload nginx
```

---

## SSL Certificate Renewal

Let's Encrypt certificates auto-renew via Certbot cron. Manual renewal if needed:

```bash
sudo certbot renew --nginx
sudo systemctl reload nginx
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| SSE stream arrives all at once | `proxy_buffering` not set to `off` | Add `proxy_buffering off` to `/api/chat/stream` location |
| Messenger webhook returns `403` | nginx buffering request body before HMAC check | Add `proxy_request_buffering off` to webhook location |
| `413 Request Entity Too Large` | File upload exceeds default nginx limit | Increase `client_max_body_size` |
| `502 Bad Gateway` | uvicorn not running | `systemctl status nexus-chat`; check logs |
| SSL cert expired | Certbot renewal failed | `certbot renew` manually; check cron job |

---

## Related Docs

- [RAG Deployment](rag-deployment.md)
- [Security & PII — Webhook Verification](../07-messenger-integration/security-pii.md)
- [Post-Deploy Verification](post-deploy-verification.md)
