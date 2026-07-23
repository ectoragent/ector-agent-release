---
name: exploratory-qa
description: "QA exploratório: charters, heurísticas, notas, bugs reproduzíveis. Triggers: exploratory testing, QA exploratório, session-based testing."
version: 1.0.0
metadata:
  ector:
    tags: [qa, builtin]
    category: qa
---

# Exploratory QA

## Quando usar
- Explorar build novo, achar edge cases, sessões de QA curtas

## Passos
1. Charter: foco + tempo (ex. 60m) + escopo.
2. Heurísticas: boundaries, interrupções, multi-user, permissões, i18n.
3. Anote passos/evidências; capture logs/screens.
4. Bug report: repro steps, esperado vs atual, severidade, ambiente.
5. Debrief: o que mais testar depois.

## Armadilhas
- Explorar sem notas (não reproduz).
- Só happy path.
- Severidade inflada/deflacionada.

## Verificação
- Bugs reproduzíveis; cobertura da charter; próximos focos claros.

