"""Consistency checks for the builtin-skills corpus.

Catches the class of bugs that's easy to introduce by hand and easy to miss
in review: broken/malformed frontmatter (the parser silently falls back to a
scalar split on bad YAML, quietly dropping nested `metadata`), name/category
drift from the directory layout, missing `Triggers:`, and duplicate skill
names. Run via `python -m tools.skills_lint` or the pytest guard in
`tests/agent/test_skills_lint.py`.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from agent.skill_utils import parse_frontmatter

REQUIRED_FRONTMATTER_FIELDS = ("name", "description", "version")
REQUIRED_SECTIONS = ("## Quando usar", "## Passos", "## Armadilhas", "## Verificação")
TRIGGERS_RE = re.compile(r"Triggers:\s*(.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class LintIssue:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _iter_skill_files(builtin_dir: Path):
    yield from sorted(builtin_dir.glob("*/*/SKILL.md"))


def lint_builtin_skills(builtin_dir: Path) -> list[LintIssue]:
    """Validate every SKILL.md under *builtin_dir*. Returns a list of issues
    (empty means the corpus is consistent)."""
    issues: list[LintIssue] = []
    seen_names: dict[str, Path] = {}

    categories = sorted(
        p.name for p in builtin_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    for category in categories:
        if not (builtin_dir / category / "DESCRIPTION.md").is_file():
            issues.append(LintIssue(f"{category}/", "categoria sem DESCRIPTION.md"))

    for skill_md in _iter_skill_files(builtin_dir):
        rel = str(skill_md.relative_to(builtin_dir))
        dir_name = skill_md.parent.name
        category_name = skill_md.parent.parent.name

        raw = skill_md.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(raw)

        if not frontmatter:
            issues.append(LintIssue(rel, "frontmatter ausente ou não parseou"))
            continue

        for field_name in REQUIRED_FRONTMATTER_FIELDS:
            if not frontmatter.get(field_name):
                issues.append(LintIssue(rel, f"campo obrigatório ausente: {field_name}"))

        name = frontmatter.get("name")
        if name and name != dir_name:
            issues.append(LintIssue(rel, f"name '{name}' != nome da pasta '{dir_name}'"))
        if name:
            if name in seen_names:
                issues.append(
                    LintIssue(rel, f"name '{name}' duplicado (já usado em {seen_names[name]})")
                )
            else:
                seen_names[name] = Path(rel)

        metadata = frontmatter.get("metadata")
        ector_meta = metadata.get("ector") if isinstance(metadata, dict) else None
        if not isinstance(ector_meta, dict):
            issues.append(
                LintIssue(
                    rel,
                    "metadata.ector ausente ou malformado "
                    "(frontmatter YAML provavelmente quebrado — checar indentação)",
                )
            )
        else:
            category_field = ector_meta.get("category")
            if category_field != category_name:
                issues.append(
                    LintIssue(
                        rel,
                        f"metadata.ector.category '{category_field}' != "
                        f"pasta da categoria '{category_name}'",
                    )
                )
            tags = ector_meta.get("tags")
            if not isinstance(tags, list) or not tags:
                issues.append(LintIssue(rel, "metadata.ector.tags ausente ou vazio"))

        description = str(frontmatter.get("description") or "")
        if not TRIGGERS_RE.search(description):
            issues.append(LintIssue(rel, "description sem 'Triggers:' (convenção do corpus)"))

        for section in REQUIRED_SECTIONS:
            if section not in body:
                issues.append(LintIssue(rel, f"seção ausente: {section}"))

        if not body.lstrip().startswith("# "):
            issues.append(LintIssue(rel, "corpo não começa com um título H1 (# Title)"))

    return issues


def main() -> int:
    from ector_constants import get_builtin_skills_dir

    builtin_dir = get_builtin_skills_dir()
    issues = lint_builtin_skills(builtin_dir)
    if not issues:
        print(f"OK — nenhum problema encontrado em {builtin_dir}")
        return 0
    print(f"{len(issues)} problema(s) encontrado(s) em {builtin_dir}:\n")
    for issue in issues:
        print(f"  - {issue}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
