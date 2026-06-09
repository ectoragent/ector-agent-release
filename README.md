<p align="center">
  <img src="https://ector.cc/_next/image?url=%2Flogo_colorful.png&w=640&q=75" alt="Ector" width="320" />
</p>

# Ector Agent

Agente de IA autoaperfeiçoável — cria skills a partir da experiência, melhora-as durante o uso e roda na sua máquina ou em gateways de mensagens.

## Início rápido

```bash
./install.sh
ector login          # identidade em https://ector.cc (obrigatório para o chat)
ector                # chat interativo no terminal (CLI) em TTY
ector chat           # idem (sem flags em TTY)
ector chat -q "oi"   # abre o CLI e envia a mensagem (TTY)
ector localhost      # painel web em http://ector.localhost:9000
ector -z "oi"        # pergunta única para scripts (one-shot; só stdout)
```

A configuração fica em `~/.ector/config.yaml`; chaves de API em `~/.ector/.env`. Para contribuir no código, veja [AGENTS.md](AGENTS.md).

Canais de mensagens suportados no gateway: **WhatsApp, Telegram, Discord e Slack**.

## Documentação

| Tópico | Onde |
|--------|------|
| Comandos da CLI | [Commands.md](Commands.md) |
| Documentação pública | https://ector.cc/docs/ |
