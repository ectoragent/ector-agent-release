---
name: network-troubleshooting
description: "Troubleshooting de rede: camada a camada, DNS→TCP→TLS→HTTP, ferramentas. Triggers: network debug, timeout, connection refused, traceroute, tcpdump."
version: 1.0.0
metadata:
  ector:
    tags: [networks, builtin]
    category: networks
---

# Network Troubleshooting

## Quando usar
- Conectividade falhando, timeouts, "não alcança o host"

## Passos
1. Reproduza; anote src/dst, porta, horário, frequência.
2. Local: IP/rota/DNS (`ip`/`ifconfig`, `route`, `dig`/`nslookup`).
3. Alcance: `ping` (se ICMP permitido), `traceroute`/`mtr`.
4. Porta: `nc`/`curl`/`openssl s_client`; interprete refused vs timeout.
5. Middleboxes: firewall, security groups, NAT, proxy corporativo.
6. Capture só com autorização (`tcpdump`/`wireshark`) e filtre.
7. Correlacione com mudanças recentes (deploy, DNS, certs).

## Armadilhas
- Culpar DNS sem verificar.
- tcpdump em prod sem cuidado (PII/volume).
- Ignorar MTU/VPN.

## Verificação
- Causa raiz documentada; teste de regressão (check contínuo) se crítico.

