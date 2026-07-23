---
name: firewall-vpn-basics
description: "Firewall e VPN: regras, least privilege, tunnels, split tunnel. Triggers: firewall, iptables, nftables, security group, VPN, wireguard."
version: 1.0.0
metadata:
  ector:
    tags: [networks, builtin]
    category: networks
---

# Firewall & VPN Basics

## Quando usar
- Abrir/fechar portas, SG/NACL, VPN site-to-site ou remote access

## Passos
1. Least privilege: allowlist por src/dst/porta; deny default.
2. Documente intenção da regra; expire regras temporárias.
3. VPN: autenticação forte; split tunnel consciente; rotas.
4. Teste acesso positivo e negativo após mudança.
5. Logue drops relevantes; alerte anomalias.

## Armadilhas
- `0.0.0.0/0` em portas admin.
- Regras duplicadas/ordem errada.
- VPN full-tunnel sem necessidade (latência/exfil risk).

## Verificação
- Só o tráfego pretendido passa; acesso admin restrito; mudança revertível.

