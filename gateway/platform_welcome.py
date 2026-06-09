"""Friendly bot /start welcome messages for messaging platforms."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from gateway.config import Platform

if TYPE_CHECKING:
    from gateway.platforms.base import MessageEvent
    from gateway.session import SessionStore

logger = logging.getLogger(__name__)

_START_COMMANDS = frozenset({"start"})


@dataclass(frozen=True)
class StartWelcomeContext:
    platform: str
    user_name: Optional[str]
    deep_link: str
    is_first_contact: bool


def is_bot_start_command(command: str | None) -> bool:
    if not command:
        return False
    return command.strip().lower().replace("_", "-") in _START_COMMANDS


def supports_bot_start_command(platform: Platform | None) -> bool:
    """Platforms where ``/start`` is a conventional onboarding command."""
    return platform in (Platform.TELEGRAM,)


def _intro_store_path(*, create_dir: bool = False) -> Path:
    from ector_constants import get_ector_home

    path = get_ector_home() / "gateway" / "bot_start_intro_seen.json"
    if create_dir:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _intro_key(source) -> str | None:
    platform = source.platform.value if source.platform else ""
    user_id = (source.user_id or "").strip()
    if not platform or not user_id:
        return None
    return f"{platform}:{user_id}"


def _load_intro_seen() -> set[str]:
    path = _intro_store_path()
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(item) for item in data if item}
        if isinstance(data, dict):
            return {key for key, seen in data.items() if seen}
    except Exception as exc:
        logger.debug("platform_welcome: could not read intro store: %s", exc)
    return set()


def _save_intro_seen(keys: set[str]) -> None:
    path = _intro_store_path(create_dir=True)
    try:
        path.write_text(
            json.dumps(sorted(keys), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("platform_welcome: could not write intro store: %s", exc)


def _has_seen_start_intro(source) -> bool:
    key = _intro_key(source)
    if not key:
        return False
    return key in _load_intro_seen()


def mark_start_intro_seen(source) -> None:
    key = _intro_key(source)
    if not key:
        return
    seen = _load_intro_seen()
    if key in seen:
        return
    seen.add(key)
    _save_intro_seen(seen)


def _user_messages_in_transcript(transcript: list) -> int:
    count = 0
    for row in transcript:
        if not isinstance(row, dict):
            continue
        if row.get("role") == "user":
            count += 1
    return count


def is_first_user_contact(session_store: "SessionStore", source) -> bool:
    """True only before any prior user message on this bot (incl. past /start)."""
    if _has_seen_start_intro(source):
        return False
    try:
        entry = session_store.get_or_create_session(source)
        transcript = session_store.load_transcript(entry.session_id)
        return _user_messages_in_transcript(transcript) == 0
    except Exception as exc:
        logger.debug("platform_welcome: could not load transcript: %s", exc)
        return False


def _static_welcome_back(ctx: StartWelcomeContext) -> str:
    name = (ctx.user_name or "").strip()
    if name:
        return f"Bem-vindo de volta, {name}! Pode mandar sua mensagem quando quiser."
    return "Bem-vindo de volta! Pode mandar sua mensagem quando quiser."


def _static_first_start_welcome(ctx: StartWelcomeContext) -> str:
    name = (ctx.user_name or "").strip()
    greeting = f"Olá, {name}!" if name else "Olá!"
    platform_label = {
        "telegram": "Telegram",
    }.get(ctx.platform, ctx.platform.title())

    lines = [
        f"{greeting} 👋",
        "",
        f"Sou o **Ector**, seu assistente de IA no {platform_label}.",
        "",
        "Você pode conversar comigo como faria com uma pessoa — "
        "perguntas, ideias, tarefas do dia a dia, código, resumos e muito mais.",
        "",
        "Exemplos do que posso fazer:",
        "• Responder dúvidas e explicar assuntos",
        "• Ajudar com textos, planos e organização",
        "• Apoiar tarefas técnicas quando você precisar",
        "",
        "Digite **/help** para ver os comandos ou simplesmente envie sua mensagem.",
    ]
    if ctx.deep_link:
        lines.extend(["", f"_(Link de entrada: {ctx.deep_link})_"])
    return "\n".join(lines)


def _build_llm_prompt(ctx: StartWelcomeContext) -> tuple[str, str]:
    platform_label = {
        "telegram": "Telegram",
    }.get(ctx.platform, ctx.platform.title())

    system = (
        "Você é o Ector, um assistente de IA amigável em apps de mensagem. "
        "Escreva APENAS a mensagem de boas-vindas em português do Brasil — "
        "sem meta-comentários, sem JSON, sem mencionar gateway, ferramentas internas "
        "ou que você é um modelo de linguagem. "
        "Tom: acolhedor, claro para usuários comuns, conciso. "
        "Use Markdown leve do Telegram (**negrito**, listas com •) quando ajudar. "
        "Máximo ~120 palavras."
    )

    user_parts = [
        f"Plataforma: {platform_label}",
        f"Usuário: {ctx.user_name or 'desconhecido'}",
        "Primeira mensagem deste usuário para este bot: sim",
    ]
    if ctx.deep_link:
        user_parts.append(f"Parâmetro do /start: {ctx.deep_link}")

    user_parts.append(
        "O usuário acabou de abrir o bot com /start pela primeira vez. "
        "Apresente o Ector, explique que pode conversar em linguagem natural "
        "(perguntas, tarefas, ideias) e convide a enviar a primeira mensagem. "
        "Mencione /help para comandos. Não seja técnico."
    )

    return system, "\n".join(user_parts)


async def _generate_first_start_welcome_via_llm(ctx: StartWelcomeContext) -> str | None:
    try:
        from openai import AsyncOpenAI

        from gateway.run import _resolve_gateway_model, _resolve_runtime_agent_kwargs

        runtime = _resolve_runtime_agent_kwargs()
        api_key = runtime.get("api_key", "")
        base_url = runtime.get("base_url") or "https://openrouter.ai/api/v1"
        model = _resolve_gateway_model()
        if not api_key or not model:
            return None

        system, user_msg = _build_llm_prompt(ctx)
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=320,
                temperature=0.65,
            )
            text = (response.choices[0].message.content or "").strip()
            return text or None
        finally:
            try:
                await client.close()
            except Exception:
                pass
    except Exception as exc:
        logger.debug("platform_welcome: LLM welcome failed: %s", exc)
        return None


async def build_bot_start_welcome(
    event: "MessageEvent",
    *,
    session_store: "SessionStore",
) -> str:
    source = event.source
    platform_key = source.platform.value if source.platform else "unknown"
    deep_link = (event.get_command_args() or "").strip()
    first_contact = is_first_user_contact(session_store, source)

    ctx = StartWelcomeContext(
        platform=platform_key,
        user_name=(source.user_name or "").strip() or None,
        deep_link=deep_link,
        is_first_contact=first_contact,
    )

    if not first_contact:
        return _static_welcome_back(ctx)

    message = await _generate_first_start_welcome_via_llm(ctx)
    if not message:
        message = _static_first_start_welcome(ctx)
    mark_start_intro_seen(source)
    return message
