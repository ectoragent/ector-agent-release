---
name: dns-http-tls
description: "DNS, HTTP e TLS: resolução, redirects, certificados, handshake. Triggers: DNS, TLS, certificate, HTTPS, curl -v, SNI."
version: 1.0.0
metadata:
  ector:
    tags: [networks, builtin]
    category: networks
---

# DNS, HTTP & TLS

## Quando usar
- Erros de certificado, DNS errado, HTTPS quebrado, redirects loops

## Passos
1. DNS: registros A/AAAA/CNAME/MX/TXT; TTL; propague com paciência medida.
2. HTTP: método, headers, status, redirects; compare `curl -vI`.
3. TLS: cadeia de certs, validade, SNI, protocolo/cipher.
4. HSTS e mixed content no browser.
5. CDN/proxy: origem vs edge; cache de erros.

## Armadilhas
- Corrigir só o cert no edge e esquecer origem.
- CNAME encadeado demais.
- Clock skew derrubando TLS.

## Verificação
- `curl`/browser ok; SSL Labs ou equivalente aceitável para o risco; DNS consistente nos resolvers relevantes.

