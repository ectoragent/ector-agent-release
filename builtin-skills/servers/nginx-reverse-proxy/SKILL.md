---
name: nginx-reverse-proxy
description: "Nginx reverse proxy: upstreams, TLS, headers, buffering, rate limit. Triggers: Nginx, reverse proxy, proxy_pass, load balancer."
version: 1.0.0
metadata:
  ector:
    tags: [servers, builtin]
    category: servers
---

# Nginx Reverse Proxy

## Quando usar
- Configurar/reparar Nginx como proxy, TLS termination, roteamento

## Passos
1. Upstream + `proxy_pass`; timeouts alinhados ao app.
2. Headers: `X-Forwarded-For/Proto`; WebSocket upgrade se preciso.
3. TLS: certs, protocolos modernos; redireciona HTTP→HTTPS.
4. Buffering/body size para uploads; limite de rate se abuso.
5. `nginx -t` antes de reload; reload graceful.
6. Logs access/error com correlação.

## Armadilhas
- Loops de redirect.
- Esquecer forwarded proto (cookies Secure / URLs).
- Timeouts menores que o backend longo.

## Verificação
- `nginx -t` ok; health endpoints; TLS válido; headers corretos no app.

