---
name: owasp-web-security
description: "OWASP Web: OWASP Top 10, controles preventivos, review de app web. Triggers: OWASP, XSS, SQLi, CSRF, SSRF, security headers."
version: 1.0.0
metadata:
  ector:
    tags: [security, builtin]
    category: security
---

# OWASP Web Security

## Quando usar
- Hardening de apps web, code review de segurança, checklist Top 10

## Passos
1. Mapeie trust boundaries (browser, API, admin, webhooks).
2. Injection: parameterized queries; escape/encoding de output (XSS).
3. Authn/z: veja `auth-sessions-jwt`; IDOR é falha comum — teste objetos por ID.
4. SSRF: allowlist de destinos; bloqueie metadata IPs.
5. Upload: type/size validation; store fora de webroot; scan se crítico.
6. Headers: CSP, HSTS, frame-ancestors; cookies seguros.
7. Dependências: audit/CVE; patch prioritário em internet-facing.

## Armadilhas
- XSS "resolvido" só com WAF.
- CSRF token ausente em cookie-session state-changing.
- Debug endpoints abertos.

## Verificação
- Checklist Top 10 percorrido; testes negativos de IDOR/XSS/SQLi nos fluxos críticos.

