"""Compact web-dashboard visual policy for the system prompt (weak-model friendly)."""


def build_web_visual_policy(*, ector_home: str, images_dir: str) -> str:
    """Return visual instructions appended to the web platform hint."""
    return f"""
## Visuais neste chat (automático — não peça permissão ao usuário)

**Quando visualizar sem ser pedido**
- Rankings, notas, comparações (3+ itens com números) → gráfico de barras ```chart
- Passos, fluxos, arquitetura → diagrama ```mermaid
- Você salvou .png/.jpg em `{images_dir}/` → a mesma resposta deve incluir `![legenda](/api/chat/images/NOME)`

**Modelo de gráfico (copie e preencha — prefira labels + values para modelos simples)**
```chart
{{"type":"bar","title":"TÍTULO","labels":["Nome A","Nome B"],"values":[4.6,4.2]}}
```
Regras: use números JSON (`4.6` não `"4,6"`). Ou array `data`: `{{"name":"A","nota":4.6}}`.

**Modelo Mermaid**
```mermaid
graph TD
  A[Início] --> B[Fim]
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
""".strip()
