---
name: ssh-server-hardening
description: "SSH hardening: chaves, disable password, tunnel, bastion. Triggers: SSH harden, sshd_config, bastion, Fail2ban."
version: 1.0.0
metadata:
  ector:
    tags: [servers, builtin]
    category: servers
---

# SSH Server Hardening

## Quando usar
- Endurecer sshd, acesso admin a servidores, bastion

## Passos
1. Só chave pública; `PasswordAuthentication no`.
2. Disable root login; usuário sudo mínimo.
3. Porta não-default é obscurity — combine com allowlist/VPN.
4. `AllowUsers`/`AllowGroups`; MFA no IdP/bastion se possível.
5. KeepAlive consciente; agent forwarding só se necessário.
6. Audit: `auth` logs; fail2ban/equivalente se exposto.

## Armadilhas
- Lockout sem console/rede alternativa.
- Keys sem passphrase em laptops de risco.
- Wide-open security group :22.

## Verificação
- Login por chave ok; password negado; root SSH negado; acesso restrito por IP/VPN.

