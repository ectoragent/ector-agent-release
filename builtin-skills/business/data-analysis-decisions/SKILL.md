---
name: data-analysis-decisions
description: "Análise de dados para decisão de negócio: pergunta certa, leitura correta, recomendação acionável. Triggers: analisar dados, análise de negócio, planilha, dashboard, insights, tomar decisão com dados."
version: 1.0.0
metadata:
  ector:
    tags: [business, builtin]
    category: business
---

# Data Analysis for Decisions

## Quando usar
- Interpretar planilha/relatório/dashboard para embasar uma decisão de negócio (não análise técnica de sistema — para isso veja `sql-analytics`/`data-anomaly-investigation`)

## Passos
1. Comece pela pergunta de decisão, não pelo dataset: "o que eu preciso decidir com isso?" — sem isso, qualquer análise vira exploração sem fim.
2. Confira a fonte e o período dos dados antes de interpretar; número certo de pergunta errada (ou período errado) engana com confiança.
3. Olhe a distribuição, não só a média — outliers e segmentos escondem histórias que a média some.
4. Separe correlação de causa: se dois números sobem juntos, pergunte o que mais mudou no mesmo período antes de atribuir causa.
5. Compare com uma referência (período anterior, meta, concorrente, benchmark) — um número sozinho não diz se é bom ou ruim.
6. Resuma em uma recomendação acionável + o nível de confiança dela, não numa lista de gráficos; quem decide precisa do "e daí".
7. Diga explicitamente o que os dados NÃO respondem — evita decisão tomada com falsa certeza.

## Armadilhas
- Confundir "os dados mostram X" com "os dados mostram tudo relevante sobre X".
- Cortar os dados de tantas formas até achar o recorte que confirma a hipótese inicial.
- Entregar dashboard/planilha sem uma conclusão — deixa o trabalho de decidir para quem só queria a resposta.

## Verificação
- A recomendação sobrevive a "e se eu olhar por outro período/segmento?" sem mudar de direção.
