#!/usr/bin/env python3
"""
Wiser — pergunta estruturada ao usuário (múltipla escolha ou texto livre).

O modelo chama ``wiser`` quando precisa de uma decisão ou informação do humano.
A UI (CLI / gateway / TUI) injeta ``wiser_callback`` no ``AIAgent``.
"""

from __future__ import annotations

import json
from typing import Any, Callable, List, Optional

from tools.registry import registry, tool_error

MAX_CHOICES = 4
MAX_QUESTION_CHARS = 4000
MAX_CONTEXT_CHARS = 600
MAX_CHOICE_CHARS = 320
MIN_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 600
DEFAULT_TIMEOUT_SECONDS = 120

# Model-facing messages (English) — keep in sync with frontend/tui WISER_USER_CANCELLED.
WISER_USER_CANCELLED = (
    "The user cancelled. Use your best judgement to proceed."
)
WISER_USER_TIMEOUT = (
    "The user did not provide a response within the time limit. "
    "Use your best judgement to make the choice and proceed."
)


def get_wiser_timeout_seconds(config: Optional[dict] = None) -> int:
    """Resolve Wiser prompt timeout from config (wiser.timeout, legacy ask_user.timeout)."""
    if config is None:
        try:
            from ector_cli.config import load_config

            config = load_config()
        except Exception:
            config = {}
    wiser_cfg = config.get("wiser") if isinstance(config.get("wiser"), dict) else {}
    ask_cfg = config.get("ask_user") if isinstance(config.get("ask_user"), dict) else {}
    raw = wiser_cfg.get("timeout") or ask_cfg.get("timeout") or DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = int(raw)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    return max(MIN_TIMEOUT_SECONDS, min(MAX_TIMEOUT_SECONDS, timeout))


def _normalize_choices(choices: Optional[List[str]]) -> tuple[Optional[List[str]], bool]:
    """Return (deduped choices up to MAX_CHOICES, was_truncated)."""
    if choices is None:
        return None, False
    if not isinstance(choices, list):
        raise TypeError("choices must be a list")
    seen: set[str] = set()
    normalized: List[str] = []
    for c in choices:
        s = str(c).strip()
        if not s or s in seen:
            continue
        if len(s) > MAX_CHOICE_CHARS:
            raise ValueError(f"choice exceeds {MAX_CHOICE_CHARS} characters")
        seen.add(s)
        normalized.append(s)
    if not normalized:
        return None, False
    truncated = len(normalized) > MAX_CHOICES
    if truncated:
        normalized = normalized[:MAX_CHOICES]
    return normalized, truncated


def _format_question_for_ui(question: str, context: Optional[str]) -> str:
    q = (question or "").strip()
    ctx = (context or "").strip()
    if not ctx:
        return q
    return f"{ctx}\n\n{q}"


def wiser_tool(
    question: str,
    choices: Optional[List[str]] = None,
    context: Optional[str] = None,
    callback: Optional[Callable[..., str]] = None,
) -> str:
    """
    Pede uma resposta ao usuário: até 4 opções fixas + "Outro", ou só texto livre.

    ``context`` (opcional) é uma linha curta de enquadramento mostrada acima da
    pergunta na UI — não substitui a pergunta no JSON devolvido ao modelo.
    """
    if not question or not str(question).strip():
        return tool_error("O parâmetro ``question`` é obrigatório.", success=False)

    question = str(question).strip()
    if len(question) > MAX_QUESTION_CHARS:
        return tool_error(
            f"Pergunta muito longa (máx. {MAX_QUESTION_CHARS} caracteres).",
            success=False,
        )

    ctx: Optional[str] = None
    if context is not None and str(context).strip():
        ctx = str(context).strip()
        if len(ctx) > MAX_CONTEXT_CHARS:
            return tool_error(
                f"``context`` muito longo (máx. {MAX_CONTEXT_CHARS} caracteres).",
                success=False,
            )

    choices_truncated = False
    normalized_choices: Optional[List[str]] = None
    if choices is not None:
        if not isinstance(choices, list):
            return tool_error("``choices`` deve ser uma lista de strings.", success=False)
        try:
            normalized_choices, choices_truncated = _normalize_choices(choices)
        except ValueError as exc:
            return tool_error(str(exc), success=False)

    if callback is None:
        return json.dumps(
            {"error": "Wiser não está disponível neste contexto (sem callback da plataforma)."},
            ensure_ascii=False,
        )

    display_question = _format_question_for_ui(question, ctx)

    try:
        user_response = callback(display_question, normalized_choices)
    except Exception as exc:
        return json.dumps(
            {"error": f"Falha ao obter resposta do usuário: {exc}"},
            ensure_ascii=False,
        )

    payload: dict[str, Any] = {
        "question": question,
        "choices_offered": normalized_choices,
        "user_response": str(user_response).strip(),
    }
    if ctx:
        payload["context"] = ctx
    if choices_truncated:
        payload["choices_truncated"] = True
    return json.dumps(payload, ensure_ascii=False)


def check_wiser_requirements() -> bool:
    return True


WISER_SCHEMA = {
    "name": "wiser",
    "description": (
        "**Wiser** — faça **uma** pergunta ao usuário quando faltar informação **que só o humano sabe**, "
        "houver trade-off real entre caminhos, ou for obrigatório escolher antes de agir.\n\n"
        "**Não use** para notícias, fatos atuais, clima, preços, versões de software, nem para pedir "
        "permissão para pesquisar na web — use ``web_search`` (ou outra ferramenta de consulta) "
        "direto e responda com o que encontrou.\n\n"
        "Modos: (1) até 4 opções em ``choices`` — a UI acrescenta “Outro”; "
        "(2) sem ``choices`` — resposta em texto livre.\n\n"
        "Use ``context`` só para uma linha curta de enquadramento (ex.: “Sobre o deploy de ontem”). "
        "Seja direto na ``question``; não empilhe várias perguntas — uma por chamada.\n\n"
        "Não use para confirmação de comando perigoso do terminal (há fluxo próprio). "
        "Para decisões triviais, prefira assumir um padrão razoável em vez de interromper o usuário."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Pergunta única, clara, na língua do usuário.",
            },
            "context": {
                "type": "string",
                "description": (
                    "Opcional. Uma ou duas frases curtas de contexto (o quê / por quê está perguntando). "
                    "Aparece na UI antes da pergunta; omita se não agregar valor."
                ),
            },
            "choices": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAX_CHOICES,
                "description": (
                    "Até 4 opções mutuamente exclusivas. Omita o parâmetro inteiro para pergunta aberta. "
                    "Redija opções curtas e paralelas (mesmo tipo de resposta)."
                ),
            },
        },
        "required": ["question"],
    },
}


registry.register(
    name="wiser",
    toolset="wiser",
    schema=WISER_SCHEMA,
    handler=lambda args, **kw: wiser_tool(
        question=args.get("question", ""),
        choices=args.get("choices"),
        context=args.get("context"),
        callback=kw.get("callback"),
    ),
    check_fn=check_wiser_requirements,
    emoji="❓",
)
