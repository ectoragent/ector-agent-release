---
name: static-site-deploy-hosting
description: "Deploy e hospedagem de sites estáticos/JAMstack: Vercel, Netlify, Cloudflare Pages, edge, domínios. Triggers: deploy site, Vercel, Netlify, Cloudflare Pages, preview deployment, custom domain, redirects, edge function."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# Deploy & Hosting de Sites Estáticos

## Quando usar
- Publicar/configurar hosting de site, preview por PR, domínio custom, redirects/headers

## Passos
1. Build reproduzível (lockfile commitado); variáveis de ambiente separadas por preview/produção.
2. Preview deployment por PR/branch — revise visualmente antes de dar merge.
3. Redirects/rewrites declarativos (arquivo de config da plataforma), não lógica ad hoc no client.
4. Headers de cache: assets com hash → cache longo/imutável; HTML → cache curto ou revalidate.
5. Domínio custom: DNS (CNAME/A conforme provedor), certificado TLS automático, decida `www` vs apex e redirecione o outro.
6. Edge functions/middleware só quando precisa de lógica por request perto do usuário (geo, A/B test, auth leve).
7. Rollback rápido disponível (voltar para deploy anterior em um clique/comando).

## Armadilhas
- Secrets de produção vazando em build de preview público.
- Redirect loop entre `www`/apex ou entre HTTP/HTTPS.
- Cache agressivo no HTML impedindo o usuário ver a versão nova publicada.

## Verificação
- Preview funciona igual produção; domínio resolve com TLS válido; rollback testado ao menos uma vez.
