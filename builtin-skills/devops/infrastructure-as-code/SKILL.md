---
name: infrastructure-as-code
description: "IaC: Terraform/Pulumi, state, módulos, drift, plano seguro. Triggers: Terraform, IaC, Pulumi, CloudFormation, terraform plan, state file, drift."
version: 1.0.0
metadata:
  ector:
    tags: [devops, builtin]
    category: devops
---

# Infrastructure as Code

## Quando usar
- Provisionar/alterar infra via código, revisar plano, resolver drift ou state travado
- Para flags/receitas do binário Terraform, use também a skill `terraform-cli`

## Passos
1. State remoto com lock (S3+DynamoDB, Terraform Cloud, etc.) — nunca state local em time.
2. Módulos pequenos e reutilizáveis; inputs/outputs explícitos; evite duplicação copy-paste.
3. `plan` sempre antes de `apply`; revise diff como um PR de código normal.
4. Environments (dev/stage/prod) isolados por state/workspace; nada de `prod` só por variável.
5. Secrets fora do state em texto puro quando possível (external secret manager); state é sensível.
6. Drift: detecte com `plan` periódico; corrija código, não faça click-ops manual.
7. Destructive changes (replace/destroy) revisadas com atenção extra antes de aplicar.

## Armadilhas
- `apply` direto em prod sem revisar plano.
- State compartilhado sem lock (corrupção em apply concorrente).
- Recursos criados manualmente no console que o IaC não conhece (drift permanente).

## Verificação
- `plan` limpo (sem diff inesperado) antes do apply; state consistente com a infra real; mudança revertível.
