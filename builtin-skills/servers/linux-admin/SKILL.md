---
name: linux-admin
description: "Administração Linux: processos, systemd, disco, usuários, logs. Triggers: Linux admin, systemd, journalctl, disk full, permissions."
version: 1.0.0
metadata:
  ector:
    tags: [servers, builtin]
    category: servers
---

# Linux Admin

## Quando usar
- Operação de servidores Linux, incidentes de disco/CPU, serviços systemd

## Passos
1. Observe: `top`/`htop`, `df`/`du`, `ss`/`lsof`, load average.
2. Serviços: `systemctl status|restart`; logs em `journalctl -u`.
3. Disco: ache diretórios grandes; rotacione logs; não delete cego em `/var`.
4. Permissões: least privilege; cuidado com `chmod 777`.
5. Usuários/SSH: chaves, sudoers mínimo (veja `ssh-server-hardening`).
6. Packages: atualize com janela; reinicie se kernel exigir.

## Armadilhas
- Matar processos sem entender dependências.
- Encher disco com logs de debug.
- Rodar serviços como root sem necessidade.

## Verificação
- Serviço healthy; espaço em disco ok; mudança documentada.

