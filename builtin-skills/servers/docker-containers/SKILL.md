---
name: docker-containers
description: "Docker: imagens enxutas, redes, volumes, segurança básica de container. Triggers: Docker, Dockerfile, compose, container, image build."
version: 1.0.0
metadata:
  ector:
    tags: [servers, builtin]
    category: servers
---

# Docker Containers

## Quando usar
- Dockerfile/compose, debug de container, hardening básico de imagem

## Passos
1. Imagens slim/distroless quando possível; pin por digest em prod.
2. USER não-root; multi-stage builds; .dockerignore.
3. Saúde: HEALTHCHECK ou probes no orquestrador.
4. Secrets via runtime secret store — não na imagem.
5. Redes/ports mínimos; volumes com cuidado de permissão.
6. Scan de imagem (CVEs) no CI.

## Armadilhas
- `latest` em produção.
- Root + privileged sem motivo.
- Camadas cache invalidando sempre (ordem de COPY).

## Verificação
- Build reproduzível; container sobe limpo; app healthy sem root.

