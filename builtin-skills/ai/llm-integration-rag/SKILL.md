---
name: llm-integration-rag
description: "Integrar LLMs em produto: prompts, RAG, tool use, avaliação, custo/latência. Triggers: LLM, RAG, prompt engineering, embeddings, vector db, system prompt, hallucination, eval."
version: 1.0.0
metadata:
  ector:
    tags: [ai, builtin]
    category: ai
---

# LLM Integration & RAG

## Quando usar
- Adicionar feature com LLM (chat, extração, geração), RAG sobre docs próprios, debugar respostas ruins/caras/lentas

## Passos
1. Separe instruções (system prompt) de dados do usuário; nunca concatene input não confiável direto no comando.
2. Prompt versionado no repo, não hardcoded espalhado; teste com casos reais, não só o feliz.
3. RAG: chunking com overlap sensato, metadata para filtro, top-k + rerank quando precisão importa.
4. Structured output (JSON schema/tool calling) em vez de parsear texto livre quando o consumidor é código.
5. Trate alucinação como esperado: cite fonte quando possível, valide contra dados reais em paths críticos.
6. Custo/latência: cache de respostas determinísticas, streaming para UX, modelo menor quando a tarefa permite.
7. Prompt injection: conteúdo externo (web, docs, tool output) é dado, não instrução — trate como não confiável.
8. Avalie com dataset de regressão (golden set) antes de mudar prompt/modelo em produção.

## Armadilhas
- Prompt gigante genérico tentando cobrir tudo em vez de tarefas focadas.
- Sem avaliação automatizada — cada mudança de prompt é "parece melhor" no olho.
- Confiar cegamente em output do LLM para decisão irreversível/financeira sem validação humana ou de sistema.
- RAG sem filtro de permissão (retorna docs que o usuário não deveria ver).

## Verificação
- Golden set passa após mudança de prompt/modelo; latência/custo por request medidos; falhas degradam graciosamente (fallback, retry, mensagem clara).
