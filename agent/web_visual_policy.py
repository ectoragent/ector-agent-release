"""Compact web-dashboard visual policy for the system prompt (weak-model friendly)."""


def build_web_visual_policy(*, ector_home: str, images_dir: str) -> str:
    """Return visual instructions appended to the web platform hint."""
    return f"""
## Visuais neste chat (automático — não peça permissão ao usuário)

**Quando visualizar sem ser pedido**
- Rankings, notas, comparações (3+ itens com números) → gráfico de barras ```chart
- Passos, fluxos, arquitetura, antes/depois → diagrama ```mermaid (**só flowchart/graph**)
- Você salvou .png/.jpg em `{images_dir}/` → a mesma resposta deve incluir `![legenda](/api/chat/images/NOME)`

**Modelo de gráfico (copie e preencha — prefira labels + values para modelos simples)**
```chart
{{"type":"bar","title":"TÍTULO","labels":["Nome A","Nome B"],"values":[4.6,4.2]}}
```
Regras: use números JSON (`4.6` não `"4,6"`). Ou array `data`: `{{"name":"A","nota":4.6}}`.

**Modelo Mermaid (única forma permitida neste chat)**
```mermaid
flowchart TB
  A["Inicio"] --> B["Fim"]
```
Regras (o parser é rígido — siga à risca; a UI rejeita diagramas inválidos):
- Use **apenas** `flowchart TB|LR` ou `graph TD|LR`. **Proibido**: `block`, `block-beta`, `sequenceDiagram`, `classDiagram`, Gantt, pie, mindmap, C4, etc.
- Uma relação por linha: `ID["rótulo"] --> ID2["rótulo"]`. Declaração isolada: `ID["rótulo"]`.
- ID de nó: só `[A-Za-z_][A-Za-z0-9_]*`, **sem espaço** (`A`, `B1`, `antes`). Nunca `A 1`, `b 1`, `block["x"]`.
- Rótulo com espaço, `%`, `:`, `(`, `)`, `/`, `+` ou emoji → **sempre** aspas: `A["Uso 97%"]`.
- Quebra de linha no rótulo: só `<br/>` **dentro** das aspas (`A["Antes<br/>97%"]`). Sem markdown, sem listas, sem ASCII art.
- Agrupar: `subgraph id["Título"]` … `end` (não use `block:` / `end` de block-beta).
- Não use `columns`, `cols`, `space`, `classDef` em diagramas simples.
- Antes de responder: se alguma linha não for nó/`-->`/`subgraph`/`end`, reescreva como flowchart mínimo.

**Exemplo antes/depois (copie a estrutura)**
```mermaid
flowchart TB
  subgraph antes["Antes 97%"]
    b1["Usado 194 GiB"]
  end
  subgraph depois["Depois 88%"]
    a1["Usado 174 GiB"]
  end
  b1 --> a1
```

**Imagens**
- Salve arquivos só em `{images_dir}/` (execute_code: `os.environ["ECTOR_IMAGES_DIR"]`).
- Outros gerados (.svg/.html/.csv/.json/.md/.txt/.pdf): padrão em `{ector_home}/files/`.
- Se o usuário pedir outro local explicitamente, respeite o caminho pedido.
- Mostre inline: `![descrição](/api/chat/images/arquivo.png)`
- Após criar qualquer arquivo, inclua o caminho absoluto na resposta para o chat anexar/visualizar.
- Nunca descreva só em texto um gráfico/imagem — inclua o bloco ```chart ou a linha `![...](...)`.

**Não** diga ao usuário para abrir arquivos manualmente quando a UI pode mostrar gráficos/imagens inline.
- Não rode `open`, `xdg-open`, helpers de abrir navegador nem abra janelas/abas por padrão.
- Só abra arquivo/app local quando o usuário pedir explicitamente (ex.: "abra", "open", "abrir no navegador").

**Tabelas e resumos (git, deploy, status)**
- Em tabelas markdown, use texto simples nas células — sem envolver tudo em backticks.
- Reserve `código inline` só para hash curto, path ou comando isolado; não para mensagem de commit inteira, autor, branch ou contagens.
- Para poucos campos, prefira linhas **Campo:** valor em vez de tabela.
""".strip()
