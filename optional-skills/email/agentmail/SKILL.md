---
name: agentmail
description: Dê ao Ector um inbox dedicado via AgentMail. Envie, receba e gerencie e-mails usando endereços “do agente” (ex.: ector-agent@agentmail.to).
version: 1.0.0
metadata:
  ector:
    tags: [email, communication, agentmail, mcp]
    category: email
---

# AgentMail — Agent-Owned Email Inboxes

## Requirements

- **AgentMail API key** (obrigatório): console AgentMail (tier grátis: 3 inboxes / 3.000 e-mails/mês).
- **Node.js 18+** (para rodar o MCP via `npx`).

## When to Use

Use this skill when you need to:

- Give the agent its own dedicated email address
- Send emails autonomously on behalf of the agent
- Receive and read incoming emails
- Manage email threads and conversations
- Sign up for services or authenticate via email
- Communicate with other agents or humans via email

This is NOT for reading the user's personal email (use himalaya or Gmail for that).
AgentMail gives the agent its own identity and inbox.

## Setup

### 1. Get an API Key

- Crie uma conta no console e gere um API key (prefixo `am_`).

### 2. Configure MCP Server

Adicione no `~/.ector/config.yaml`.

Nota: as variáveis em `mcp_servers.<name>.env` são definidas inline; não dependa de expansão automática do `.env`.

```yaml
mcp_servers:
  agentmail:
    command: "npx"
    args: ["-y", "agentmail-mcp"]
    env:
      AGENTMAIL_API_KEY: "am_your_key_here"
```

### 3. Restart Ector

```bash
ector
```

As ferramentas do AgentMail ficam disponíveis automaticamente.

## Ferramentas (via MCP)

- `list_inboxes`: list all agent inboxes
- `get_inbox`: get details of a specific inbox
- `create_inbox`: create a new inbox (gets a real email address)
- `delete_inbox`: delete an inbox
- `list_threads`: list email threads in an inbox
- `get_thread`: get a specific email thread
- `send_message`: send a new email
- `reply_to_message`: reply to an existing email
- `forward_message`: forward an email
- `update_message`: update message labels/status
- `get_attachment`: download an email attachment

## Procedure

### Create an inbox and send an email

1. Create a dedicated inbox:
   - Use `create_inbox` with a username (e.g. `ector-agent`)
   - The agent gets address: `ector-agent@agentmail.to`
2. Send an email:
   - Use `send_message` with `inbox_id`, `to`, `subject`, `text`
3. Check for replies:
   - Use `list_threads` to see incoming conversations
   - Use `get_thread` to read a specific thread

### Check incoming email

1. Use `list_inboxes` to find your inbox ID
2. Use `list_threads` with the inbox ID to see conversations
3. Use `get_thread` to read a thread and its messages

### Reply to an email

1. Get the thread with `get_thread`
2. Use `reply_to_message` with the message ID and your reply text

## Example Workflows

**Sign up for a service:**

```text
1. create_inbox (username: "signup-bot")
2. Use the inbox address to register on the service
3. list_threads to check for verification email
4. get_thread to read the verification code
```

**Agent-to-human outreach:**

```text
1. create_inbox (username: "ector-outreach")
2. send_message (to: user@example.com, subject: "Hello", text: "...")
3. list_threads to check for replies
```

## Pitfalls

- Free tier limited to 3 inboxes and 3,000 emails/month
- Emails come from `@agentmail.to` domain on free tier (custom domains on paid plans)
- Node.js (18+) is required for the MCP server (`npx -y agentmail-mcp`)
- Inbound “real time” via webhook requer servidor público; para uso pessoal, use polling (`list_threads`) via cronjob.

## Verification

After setup, test with:

```bash
ector --toolsets mcp -q "Create an AgentMail inbox called test-agent and tell me its email address"
```

You should see the new inbox address returned.

## References

- AgentMail docs: `https://docs.agentmail.to/`
- Console: `https://console.agentmail.to`
- MCP repo: `https://github.com/agentmail-to/agentmail-mcp`
- Pricing: `https://www.agentmail.to/pricing`
