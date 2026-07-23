---
name: seo-technical
description: "SEO técnico para web: meta tags, structured data, sitemap, indexação, Core Web Vitals. Triggers: SEO, meta tags, Open Graph, structured data, schema.org, sitemap.xml, robots.txt, indexação."
version: 1.0.0
metadata:
  ector:
    tags: [frontend, builtin]
    category: frontend
---

# SEO Técnico

## Quando usar
- Lançar/revisar site indexável no Google, corrigir queda de tráfego orgânico, preparar site novo para SEO

## Passos
1. HTML semântico + um `<h1>` por página; hierarquia de headings lógica (sem pular níveis).
2. `<title>` e `meta description` únicos por página, escritos para humano — não empilhados de keyword.
3. `canonical` sempre presente; `hreflang` se multi-idioma; evite conteúdo duplicado acessível por várias URLs.
4. Structured data (schema.org/JSON-LD) para o tipo de conteúdo: Article, Product, Organization, FAQ, BreadcrumbList.
5. Open Graph/Twitter Card (`og:title`, `og:description`, `og:image`) para preview correto ao compartilhar.
6. `sitemap.xml` atualizado e referenciado no `robots.txt`; `robots.txt` não pode bloquear CSS/JS nem páginas que devem indexar.
7. Conteúdo crítico renderizado no server (SSR/SSG) — não confie só em client-side render para o crawler ver o texto.
8. Core Web Vitals bons (ver `frontend-performance`) — é fator de ranking direto, não só UX.

## Armadilhas
- Bloquear CSS/JS no `robots.txt` (Google não consegue renderizar a página corretamente).
- Conteúdo só em client-side render sem fallback SSR/SSG.
- Título/description genéricos duplicados via template em várias páginas.

## Verificação
- Search Console sem erros de indexação/cobertura; teste de rich results passa; Lighthouse SEO ~100.
