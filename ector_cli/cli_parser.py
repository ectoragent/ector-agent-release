"""Argparse tree for the ``ector`` CLI."""

from __future__ import annotations

import argparse
import difflib
import re
import sys

_INVALID_CHOICE_RE = re.compile(
    r"argument \S+: invalid choice: '(?P<choice>.*)' \(choose from (?P<choices>.+)\)\s*$"
)
_UNRECOGNIZED_ARGS_RE = re.compile(
    r"unrecognized arguments?: (?P<args>.+)\s*$"
)


class EctorArgumentParser(argparse.ArgumentParser):
    """ArgumentParser with concise, pt-BR error messages for common typos."""

    def add_subparsers(self, *args, **kwargs):
        kwargs.setdefault("parser_class", type(self))
        return super().add_subparsers(*args, **kwargs)

    def error(self, message: str) -> None:
        match = _INVALID_CHOICE_RE.search(message)
        if match:
            self._exit_invalid_choice(match.group("choice"), match.group("choices"))
        match = _UNRECOGNIZED_ARGS_RE.search(message)
        if match:
            self._exit_unrecognized_args(match.group("args"))
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {message}\n")

    @staticmethod
    def _error_console():
        from rich.console import Console

        return Console(stderr=True, highlight=False)

    def _exit_cli_error(self, *lines: str) -> None:
        console = self._error_console()
        for line in lines:
            console.print(line)
        sys.exit(2)

    def _exit_invalid_choice(self, choice: str, choices_blob: str) -> None:
        choices = re.findall(r"'([^']*)'", choices_blob)
        suggestions = difflib.get_close_matches(choice, choices, n=3, cutoff=0.5)
        lines = [
            f"[red]✖[/red] comando inválido [bold]«{choice}»[/bold]"
            f" [dim]({self.prog})[/dim]"
        ]
        if suggestions:
            if len(suggestions) == 1:
                lines.append(
                    f"  [dim]→[/dim] Você quis dizer [cyan]{suggestions[0]}[/cyan]?"
                )
            else:
                sug_text = ", ".join(f"[cyan]{s}[/cyan]" for s in suggestions)
                lines.append(f"  [dim]→[/dim] Você quis dizer: {sug_text}?")
        lines.append(
            f"  [dim]→[/dim] Liste os comandos com: [cyan]{self.prog} --help[/cyan]"
        )
        self._exit_cli_error(*lines)

    def _exit_unrecognized_args(self, args_blob: str) -> None:
        self._exit_cli_error(
            f"[red]✖[/red] argumento(s) não reconhecido(s): [bold]{args_blob}[/bold]"
            f" [dim]({self.prog})[/dim]",
            f"  [dim]→[/dim] Use [cyan]{self.prog} --help[/cyan] para ver as opções.",
        )


def _add_accept_hooks_flag(parser) -> None:
    parser.add_argument(
        "--accept-hooks",
        action="store_true",
        default=argparse.SUPPRESS,
        help=(
            "Auto-approve unseen shell hooks without a TTY prompt "
            "(equivalent to ECTOR_ACCEPT_HOOKS=1 / hooks_auto_accept: true)."
        ),
    )


def build_parser():
    """Construct the root parser and all subparsers."""
    from ector_cli import main as _m

    parser = EctorArgumentParser(
        prog="ector",
        description="Ector Agent - Assistente de IA com capacidades de chamada de ferramentas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    Exemplos:
    ector                        Abre o painel web local (chat em /chat)
    ector --up-online            Painel atrás de Nginx (VPS)
    ector kill                   Encerra o painel em execução
    ector setup                  Executa o assistente de configuração
    ector logout                 Limpa a autenticação armazenada
    ector auth add <provedor>    Adiciona uma credencial ao pool
    ector auth list              Lista credenciais do pool
    ector auth remove <p> <t>    Remove credencial do pool por índice, id ou rótulo
    ector auth reset <provedor>  Limpa o status de esgotamento de um provedor
    ector provider               Seleciona o provedor/modelo padrão
    ector fallback [list]        Mostra a cadeia de provedores de fallback
    ector fallback add           Adiciona um provedor de fallback (mesmo seletor de `ector provider`)
    ector fallback remove        Remove um provedor de fallback da cadeia
    ector config                 Visualiza a configuração
    ector config edit            Edita a config no $EDITOR
    ector gateway                Executa o gateway de mensagens
    ector gateway install        Instala o serviço de segundo plano do gateway
    ector sessions list          Lista sessões passadas
    ector sessions browse        Seletor de sessão interativo
    ector sessions rename ID T   Renomeia/titula uma sessão
    ector logs                   Visualiza agent.log (últimas 50 linhas)
    ector logs -f                Acompanha agent.log em tempo real
    ector logs errors            Visualiza errors.log
    ector logs --since 1h        Linhas da última hora
    ector debug share             Envia relatório de depuração para suporte

    Para mais ajuda em um comando:
    ector <comando> --help
    """,
    )

    parser.add_argument(
        "--version", "-V", action="store_true", help="Mostra a versão e sai"
    )
    parser.add_argument("--port", type=int, default=9000, help="Porta do painel (padrão 9000)")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host de bind (padrão 127.0.0.1; URL amigável: ector.localhost)",
    )
    parser.add_argument(
        "--public-host",
        dest="public_host",
        default=None,
        help="Host público para compor a URL impressa (ex: IP da VPS ou domínio). Também aceita ECTOR_DASHBOARD_PUBLIC_HOST.",
    )
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Desativa a exigência de token/cookie para o painel (NÃO recomendado)",
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Mantém o painel no foreground (bloqueia o terminal)",
    )
    parser.add_argument(
        "--open-firewall",
        action="store_true",
        help="(Linux) Tenta liberar automaticamente a porta no firewall do SO (ufw/firewalld) via sudo -n",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Não abre o navegador automaticamente",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Permite binding para IPs além de localhost (PERIGOSO: expõe chaves API na rede)",
    )
    parser.add_argument(
        "--up-online",
        action="store_true",
        help="Configura Nginx + TLS/BasicAuth e inicia o painel atrás do proxy (recomendado para VPS)",
    )
    parser.add_argument(
        "--server-name",
        default="_",
        help="Server name do Nginx (domínio ou '_'). Para IP-only, deixe '_' (padrão).",
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        default=9000,
        help="Porta pública do Nginx (padrão: 9000).",
    )
    parser.add_argument(
        "--tls",
        action="store_true",
        help="Habilita TLS via Certbot (requer domínio real em --server-name e --email).",
    )
    parser.add_argument(
        "--email",
        default=None,
        help="E-mail para Certbot (obrigatório quando usar --tls).",
    )
    parser.add_argument(
        "--basic-auth",
        action="store_true",
        help="Habilita Basic Auth no Nginx (senha via prompt).",
    )
    parser.add_argument(
        "--basic-user",
        default="ector",
        help="Usuário do Basic Auth (padrão: ector).",
    )
    parser.add_argument(
        "--allow-ip",
        action="append",
        default=[],
        help="IP/CIDR permitido (pode repetir).",
    )
    parser.add_argument(
        "--upstream-port",
        type=int,
        default=9000,
        help="Porta local do painel atrás do Nginx (padrão: 9000).",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    kill_parser = subparsers.add_parser(
        "kill",
        help="Finaliza o painel web (PID file, processos Ector, ou porta --port)",
    )
    kill_parser.add_argument(
        "--port",
        type=int,
        default=9000,
        help="Porta do painel a procurar/encerrar (padrão 9000)",
    )
    kill_parser.set_defaults(func=_m.cmd_dashboard)

    # =========================================================================
    # provider command
    # =========================================================================
    provider_parser = subparsers.add_parser(
        "provider",
        help="Seleciona o provedor/modelo padrão",
        description="Seleciona interativamente seu provedor de inferência e modelo padrão",
    )
    provider_parser.add_argument(
        "--portal-url",
        help="URL base do portal para login no Ector (padrão: portal de produção)",
    )
    provider_parser.add_argument(
        "--inference-url",
        help="URL base da API de inferência para login no Ector (padrão: API de inferência de produção)",
    )
    provider_parser.add_argument(
        "--client-id",
        default=None,
        help="ID do cliente OAuth para usar no login no Ector (padrão: ector-cli)",
    )
    provider_parser.add_argument(
        "--scope", default=None, help="Escopo OAuth para solicitar no login no Ector"
    )
    provider_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Não tenta abrir o navegador automaticamente durante o login no Ector",
    )
    provider_parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Tempo limite da requisição HTTP em segundos para o login no Ector (padrão: 15)",
    )
    provider_parser.add_argument(
        "--ca-bundle", help="Caminho para o arquivo PEM do pacote CA para verificação TLS do Ector"
    )
    provider_parser.add_argument(
        "--insecure",
        action="store_true",
        help="Desativa a verificação TLS para o login no Ector (apenas para testes)",
    )
    provider_parser.set_defaults(func=_m.cmd_provider)

    # =========================================================================
    # fallback command — manage the fallback provider chain
    # =========================================================================
    from ector_cli.fallback_cmd import cmd_fallback

    fallback_parser = subparsers.add_parser(
        "fallback",
        help="Gerencia provedores de fallback (tentados quando o modelo primário falha)",
        description=(
            "Gerencia a cadeia de provedores de fallback. Provedores de fallback são tentados "
            "em ordem quando o modelo primário falha com erros de limite de taxa, sobrecarga ou "
            "conexão. Veja: "
            "https://ector.cc/docs/user-guide/features/fallback-providers"
        ),
    )
    fallback_subparsers = fallback_parser.add_subparsers(dest="fallback_command")
    fallback_subparsers.add_parser(
        "list",
        aliases=["ls"],
        help="Mostra a cadeia de fallback atual (padrão quando não há subcomando)",
    )
    fallback_subparsers.add_parser(
        "add",
        help="Escolhe um provedor + modelo (mesmo seletor de `ector provider`) e anexa à cadeia",
    )
    fallback_subparsers.add_parser(
        "remove",
        aliases=["rm"],
        help="Escolhe uma entrada para excluir da cadeia",
    )
    fallback_subparsers.add_parser(
        "clear",
        help="Remove todas as entradas de fallback",
    )
    fallback_parser.set_defaults(func=cmd_fallback)

    # =========================================================================
    # gateway command
    # =========================================================================
    gateway_parser = subparsers.add_parser(
        "gateway",
        help="Gerenciamento do gateway de mensagens",
        description="Gerencia o gateway de mensagens (Telegram, Discord, WhatsApp)",
    )
    gateway_subparsers = gateway_parser.add_subparsers(dest="gateway_command")

    # gateway run (default)
    gateway_run = gateway_subparsers.add_parser(
        "run", help="Executa o gateway em primeiro plano (recomendado para WSL, Docker, Termux)"
    )
    gateway_run.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Aumenta a verbosidade dos logs no stderr (-v=INFO, -vv=DEBUG)",
    )
    gateway_run.add_argument(
        "-q", "--quiet", action="store_true", help="Suprime toda a saída de log no stderr"
    )
    gateway_run.add_argument(
        "--replace",
        action="store_true",
        help="Substitui qualquer instância existente do gateway (útil para o systemd)",
    )
    _add_accept_hooks_flag(gateway_run)
    _add_accept_hooks_flag(gateway_parser)

    # gateway start
    gateway_start = gateway_subparsers.add_parser(
        "start", help="Inicia o serviço de segundo plano systemd/launchd instalado"
    )
    gateway_start.add_argument(
        "--system",
        action="store_true",
        help="Alvo é o serviço de gateway em nível de sistema do Linux",
    )
    gateway_start.add_argument(
        "--all",
        action="store_true",
        help="Finaliza TODOS os processos de gateway obsoletos em todos os perfis antes de iniciar",
    )

    # gateway stop
    gateway_stop = gateway_subparsers.add_parser("stop", help="Para o serviço do gateway")
    gateway_stop.add_argument(
        "--system",
        action="store_true",
        help="Alvo é o serviço de gateway em nível de sistema do Linux",
    )
    gateway_stop.add_argument(
        "--all",
        action="store_true",
        help="Para TODOS os processos de gateway em todos os perfis",
    )

    # gateway restart
    gateway_restart = gateway_subparsers.add_parser(
        "restart", help="Reinicia o serviço do gateway"
    )
    gateway_restart.add_argument(
        "--system",
        action="store_true",
        help="Alvo é o serviço de gateway em nível de sistema do Linux",
    )
    gateway_restart.add_argument(
        "--all",
        action="store_true",
        help="Finaliza TODOS os processos de gateway em todos os perfis antes de reiniciar",
    )

    # gateway status
    gateway_status = gateway_subparsers.add_parser("status", help="Mostra o status do gateway")
    gateway_status.add_argument("--deep", action="store_true", help="Verificação profunda de status")
    gateway_status.add_argument(
        "-l",
        "--full",
        action="store_true",
        help="Mostra a saída completa do serviço/log, sem truncamento, onde suportado",
    )
    gateway_status.add_argument(
        "--system",
        action="store_true",
        help="Alvo é o serviço de gateway em nível de sistema do Linux",
    )

    # gateway install
    gateway_install = gateway_subparsers.add_parser(
        "install", help="Instala o gateway como um serviço de segundo plano systemd/launchd"
    )
    gateway_install.add_argument("--force", action="store_true", help="Força a reinstalação")
    gateway_install.add_argument(
        "--system",
        action="store_true",
        help="Instala como um serviço em nível de sistema do Linux (inicia no boot)",
    )
    gateway_install.add_argument(
        "--run-as-user",
        dest="run_as_user",
        help="Conta de usuário sob a qual o serviço de sistema do Linux deve rodar",
    )

    # gateway uninstall
    gateway_uninstall = gateway_subparsers.add_parser(
        "uninstall", help="Desinstala o serviço do gateway"
    )
    gateway_uninstall.add_argument(
        "--system",
        action="store_true",
        help="Alvo é o serviço de gateway em nível de sistema do Linux",
    )

    # gateway setup
    gateway_subparsers.add_parser("setup", help="Configura as plataformas de mensagens")

    # gateway migrate-legacy
    gateway_migrate_legacy = gateway_subparsers.add_parser(
        "migrate-legacy",
        help="Remove unidades ector.service legadas de instalações anteriores à renomeação",
        description=(
            "Para, desativa e remove arquivos de unidade do gateway Ector legados "
            "(ex: ector.service) restantes de instalações antigas. Unidades de "
            "perfil (ector-gateway-<profile>.service) e serviços de terceiros "
            "não relacionados nunca são tocados."
        ),
    )
    gateway_migrate_legacy.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Lista o que seria removido sem de fato remover",
    )
    gateway_migrate_legacy.add_argument(
        "-y",
        "--yes",
        dest="yes",
        action="store_true",
        help="Pula o prompt de confirmação",
    )

    gateway_parser.set_defaults(func=_m.cmd_gateway)

    # =========================================================================
    # setup command
    # =========================================================================
    setup_parser = subparsers.add_parser(
        "setup",
        help="Assistente de configuração interativo",
        description="Configura o Ector Agent com um assistente interativo. "
        "Execute uma seção específica: ector setup model|tts|terminal|gateway|tools|agent",
    )
    setup_parser.add_argument(
        "section",
        nargs="?",
        choices=["model", "tts", "terminal", "gateway", "tools", "agent"],
        default=None,
        help="Executa uma seção de configuração específica em vez do assistente completo",
    )
    setup_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Modo não interativo (usa padrões/variáveis de ambiente)",
    )
    setup_parser.add_argument(
        "--reset", action="store_true", help="Redefine a configuração para os padrões"
    )
    setup_parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="(Padrão em instalações existentes.) Executa novamente o assistente completo, "
             "mostrando os valores atuais como padrões. Mantido para compatibilidade — "
             "um simples 'ector setup' agora faz isso.",
    )
    setup_parser.add_argument(
        "--quick",
        action="store_true",
        help="Em instalações existentes: solicita apenas itens que estão faltando "
             "ou não definidos, em vez de executar o assistente completo de reconfiguração.",
    )
    setup_parser.set_defaults(func=_m.cmd_setup)

    # =========================================================================
    # whatsapp command
    # =========================================================================
    whatsapp_parser = subparsers.add_parser(
        "whatsapp",
        help="Configura a integração com o WhatsApp",
        description="Configura o WhatsApp e emparelha via código QR",
    )
    whatsapp_parser.set_defaults(func=_m.cmd_whatsapp)

    # =========================================================================
    # slack command
    # =========================================================================
    slack_parser = subparsers.add_parser(
        "slack",
        help="Auxiliares de integração com o Slack (geração de manifesto, etc.)",
        description="Auxiliares de integração com o Slack para o Ector.",
    )
    slack_sub = slack_parser.add_subparsers(dest="slack_command")
    slack_manifest = slack_sub.add_parser(
        "manifest",
        help="Imprime ou escreve um manifesto de app do Slack com cada comando de gateway "
             "registrado como um slash nativo (/btw, /stop, /provider, ...)",
        description=(
             "Gera um manifesto de app do Slack que registra cada comando de gateway "
             "no COMMAND_REGISTRY como um comando slash do Slack de primeira classe "
             "(igualando a paridade do Discord e Telegram). Cole a saída no "
             "config do app Slack → Features → App Manifest → Edit, então Save. "
             "Reinstale o app se o Slack solicitar.",
        ),
    )
    slack_manifest.add_argument(
        "--write",
        nargs="?",
        const=True,
        default=None,
        metavar="CAMINHO",
        help="Escreve o manifesto em um arquivo em vez do stdout. Sem CAMINHO "
             "escreve em $ECTOR_HOME/slack-manifest.json.",
    )
    slack_manifest.add_argument(
        "--name",
        default=None,
        help='Nome de exibição do bot (padrão: "Ector")',
    )
    slack_manifest.add_argument(
        "--description",
        default=None,
        help="Descrição do bot mostrada no diretório de apps do Slack.",
    )
    slack_manifest.add_argument(
        "--slashes-only",
        action="store_true",
        help="Emite apenas o array features.slash_commands (para mesclar "
             "manualmente em um manifesto existente).",
    )
    slack_parser.set_defaults(func=_m.cmd_slack)

    # =========================================================================
    # login command
    # =========================================================================
    login_parser = subparsers.add_parser(
        "login",
        help="Autentica no Ector (ector.cc) ou em um provedor de inferência",
        description=(
            "Sem --provider: faz login da sua conta Ector contra o backend "
            "configurado (padrão: https://ector.cc). Com --provider, executa "
            "o fluxo OAuth legado para credenciais de inferência."
        ),
    )
    login_parser.add_argument(
        "--provider",
        choices=["openai-codex"],
        default=None,
        help="Provedor de inferência para autenticar (omitir para login de identidade)",
    )
    identity_login = login_parser.add_argument_group(
        "login de identidade (padrão, sem --provider)",
    )
    identity_login.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Força um novo login mesmo que já exista uma sessão",
    )
    identity_login.add_argument(
        "--no-browser",
        action="store_true",
        help="Não tenta abrir o navegador automaticamente",
    )
    identity_login.add_argument(
        "--callback-timeout",
        type=float,
        default=None,
        dest="callback_timeout",
        metavar="SECONDS",
        help=(
            "Tempo máximo de espera pelo callback do navegador durante o login "
            "(padrão: auth.callback_timeout_seconds em config.yaml, normalmente 180)"
        ),
    )
    identity_login.add_argument(
        "--device",
        action="store_true",
        default=False,
        help="Força login remoto por código de dispositivo (SSH/headless; sem 127.0.0.1)",
    )
    identity_login.add_argument(
        "--local",
        action="store_true",
        default=False,
        help="Força login com callback local (127.0.0.1), mesmo em sessão SSH",
    )
    provider_login = login_parser.add_argument_group(
        "login de provedor (requer --provider)",
    )
    provider_login.add_argument(
        "--portal-url", help="URL base do portal (padrão: portal de produção)"
    )
    provider_login.add_argument(
        "--inference-url",
        help="URL base da API de inferência (padrão: API de inferência de produção)",
    )
    provider_login.add_argument(
        "--client-id", default=None, help="ID do cliente OAuth para usar (padrão: ector-cli)"
    )
    provider_login.add_argument("--scope", default=None, help="Escopo OAuth para solicitar")
    provider_login.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Tempo limite HTTP do fluxo OAuth do provedor em segundos (padrão: 15)",
    )
    provider_login.add_argument(
        "--ca-bundle", help="Caminho para o arquivo PEM do pacote CA para verificação TLS"
    )
    provider_login.add_argument(
        "--insecure",
        action="store_true",
        help="Desativa a verificação TLS (apenas para testes)",
    )
    login_parser.set_defaults(func=_m.cmd_login)

    # =========================================================================
    # logout command
    # =========================================================================
    logout_parser = subparsers.add_parser(
        "logout",
        help="Encerra a sessão Ector (ou de um provedor com --provider)",
        description=(
            "Sem --provider: revoga a sessão de identidade contra ector.cc "
            "(POST /agent/auth/logout) e apaga ~/.ector/identity.json. "
            "Com --provider: limpa as credenciais do provedor de inferência."
        ),
    )
    logout_parser.add_argument(
        "--provider",
        choices=["openai-codex"],
        default=None,
        help="Provedor de inferência para deslogar (omitir para logout de identidade)",
    )
    logout_parser.set_defaults(func=_m.cmd_logout)

    # =========================================================================
    # me command
    # =========================================================================
    me_parser = subparsers.add_parser(
        "me",
        help="Mostra nickname, usuário e status da sessão Ector",
        description="Consulta a identidade autenticada (nickname, email, status da sessão).",
    )
    me_parser.add_argument(
        "--refresh",
        action="store_true",
        default=False,
        help="Ignora o cache local e bate em /agent/auth/me",
    )
    me_parser.set_defaults(func=_m.cmd_me)

    auth_parser = subparsers.add_parser(
        "auth",
        help="Gerencia credenciais de provedores no pool",
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_action")
    auth_add = auth_subparsers.add_parser("add", help="Adiciona uma credencial ao pool")
    auth_add.add_argument(
        "provider",
        help="ID do provedor (por exemplo: anthropic, openai-codex, openrouter)",
    )
    auth_add.add_argument(
        "--type",
        dest="auth_type",
        choices=["oauth", "api-key", "api_key"],
        help="Tipo de credencial a adicionar",
    )
    auth_add.add_argument("--label", help="Rótulo de exibição opcional")
    auth_add.add_argument(
        "--api-key", help="Valor da chave API (caso contrário, solicitado com segurança)"
    )
    auth_add.add_argument("--portal-url", help="Ector portal base URL")
    auth_add.add_argument("--inference-url", help="Ector inference base URL")
    auth_add.add_argument("--client-id", help="ID do cliente OAuth")
    auth_add.add_argument("--scope", help="Sobrescrita do escopo OAuth")
    auth_add.add_argument(
        "--no-browser",
        action="store_true",
        help="Não abre automaticamente um navegador para login OAuth",
    )
    auth_add.add_argument(
        "--timeout", type=float, help="Tempo limite de rede/OAuth em segundos"
    )
    auth_add.add_argument(
        "--insecure",
        action="store_true",
        help="Desativa a verificação TLS para login OAuth",
    )
    auth_add.add_argument("--ca-bundle", help="Pacote CA personalizado para login OAuth")
    auth_list = auth_subparsers.add_parser("list", help="Lista credenciais do pool")
    auth_list.add_argument("provider", nargs="?", help="Filtro de provedor opcional")
    auth_remove = auth_subparsers.add_parser(
        "remove", help="Remove uma credencial do pool por índice, id ou rótulo"
    )
    auth_remove.add_argument("provider", help="ID do provedor")
    auth_remove.add_argument(
        "target", help="Índice da credencial, id da entrada ou rótulo exato"
    )
    auth_reset = auth_subparsers.add_parser(
        "reset", help="Limpa o status de esgotamento de todas as credenciais de um provedor"
    )
    auth_reset.add_argument("provider", help="ID do provedor")
    auth_status = auth_subparsers.add_parser("status", help="Mostra o status de autenticação de um provedor")
    auth_status.add_argument("provider", help="ID do provedor")
    auth_logout = auth_subparsers.add_parser("logout", help="Faz logout de um provedor e limpa o estado de autenticação armazenado")
    auth_logout.add_argument("provider", help="ID do provedor")
    auth_parser.set_defaults(func=_m.cmd_auth)

    # =========================================================================
    # status command
    # =========================================================================
    status_parser = subparsers.add_parser(
        "status",
        help="Mostra o status de todos os componentes",
        description="Exibe o status dos componentes do Ector Agent",
    )
    status_parser.add_argument(
        "--all", action="store_true", help="Mostra todos os detalhes (redigido para compartilhamento)"
    )
    status_parser.add_argument(
        "--deep", action="store_true", help="Executa verificações profundas (pode demorar mais)"
    )
    status_parser.set_defaults(func=_m.cmd_status)

    # =========================================================================
    # cron command
    # =========================================================================
    cron_parser = subparsers.add_parser(
        "cron", help="Gerenciamento de tarefas cron", description="Gerencia tarefas agendadas"
    )
    cron_subparsers = cron_parser.add_subparsers(dest="cron_command")

    # cron list
    cron_list = cron_subparsers.add_parser("list", help="Lista tarefas agendadas")
    cron_list.add_argument("--all", action="store_true", help="Inclui tarefas desativadas")

    # cron create/add
    cron_create = cron_subparsers.add_parser(
        "create", aliases=["add"], help="Cria uma tarefa agendada"
    )
    cron_create.add_argument(
        "schedule", help="Agendamento como '30m', 'every 2h', ou '0 9 * * *'"
    )
    cron_create.add_argument(
        "prompt", nargs="?", help="Prompt opcional ou instrução de tarefa"
    )
    cron_create.add_argument("--name", help="Nome amigável opcional para a tarefa")
    cron_create.add_argument(
        "--deliver",
        help="Alvo de entrega: origin, local, telegram, discord, signal, ou platform:chat_id",
    )
    cron_create.add_argument("--repeat", type=int, help="Contagem opcional de repetições")
    cron_create.add_argument(
        "--skill",
        dest="skills",
        action="append",
        help="Anexa uma skill. Repita para adicionar múltiplas skills.",
    )
    cron_create.add_argument(
        "--script",
        help="Caminho para um script Python cuja saída padrão (stdout) é injetada no prompt a cada execução",
    )
    cron_create.add_argument(
        "--workdir",
        help="Caminho absoluto para a tarefa ser executada. Injeta AGENTS.md / CLAUDE.md / .cursorrules daquele diretório e o usa como cwd para as ferramentas de terminal/arquivo/exec_code. Omita para preservar o comportamento antigo (sem arquivos de contexto do projeto).",
    )

    # cron edit
    cron_edit = cron_subparsers.add_parser(
        "edit", help="Edita uma tarefa agendada existente"
    )
    cron_edit.add_argument("job_id", help="ID da tarefa para editar")
    cron_edit.add_argument("--schedule", help="Novo agendamento")
    cron_edit.add_argument("--prompt", help="Novo prompt/instrução de tarefa")
    cron_edit.add_argument("--name", help="Novo nome da tarefa")
    cron_edit.add_argument("--deliver", help="Novo alvo de entrega")
    cron_edit.add_argument("--repeat", type=int, help="Nova contagem de repetições")
    cron_edit.add_argument(
        "--skill",
        dest="skills",
        action="append",
        help="Substitui as skills da tarefa por este conjunto. Repita para anexar múltiplas skills.",
    )
    cron_edit.add_argument(
        "--add-skill",
        dest="add_skills",
        action="append",
        help="Anexa uma skill sem substituir a lista existente. Repetível.",
    )
    cron_edit.add_argument(
        "--remove-skill",
        dest="remove_skills",
        action="append",
        help="Remove uma skill anexada específica. Repetível.",
    )
    cron_edit.add_argument(
        "--clear-skills",
        action="store_true",
        help="Remove todas as skills anexadas da tarefa",
    )
    cron_edit.add_argument(
        "--script",
        help="Caminho para um script Python cuja saída padrão (stdout) é injetada no prompt a cada execução. Passe uma string vazia para limpar.",
    )
    cron_edit.add_argument(
        "--workdir",
        help="Caminho absoluto para a tarefa ser executada (injeta AGENTS.md etc. e define o cwd do terminal). Passe uma string vazia para limpar.",
    )

    # lifecycle actions
    cron_pause = cron_subparsers.add_parser("pause", help="Pausa uma tarefa agendada")
    cron_pause.add_argument("job_id", help="ID da tarefa para pausar")

    cron_resume = cron_subparsers.add_parser("resume", help="Retoma uma tarefa pausada")
    cron_resume.add_argument("job_id", help="ID da tarefa para retomar")

    cron_run = cron_subparsers.add_parser(
        "run", help="Executa uma tarefa no próximo ciclo do agendador"
    )
    cron_run.add_argument("job_id", help="ID da tarefa para disparar")
    _add_accept_hooks_flag(cron_run)

    cron_remove = cron_subparsers.add_parser(
        "remove", aliases=["rm", "delete"], help="Remove uma tarefa agendada"
    )
    cron_remove.add_argument("job_id", help="ID da tarefa para remover")

    # cron status
    cron_subparsers.add_parser("status", help="Verifica se o agendador cron está rodando")

    # cron tick (mostly for debugging)
    cron_tick = cron_subparsers.add_parser("tick", help="Executa tarefas pendentes uma vez e sai")
    _add_accept_hooks_flag(cron_tick)
    _add_accept_hooks_flag(cron_parser)
    cron_parser.set_defaults(func=_m.cmd_cron)

    # =========================================================================
    # webhook command
    # =========================================================================
    webhook_parser = subparsers.add_parser(
        "webhook",
        help="Gerencia inscrições de webhooks dinâmicos",
        description="Cria, lista e remove inscrições de webhooks para ativação do agente orientada a eventos",
    )
    webhook_subparsers = webhook_parser.add_subparsers(dest="webhook_action")

    wh_sub = webhook_subparsers.add_parser(
        "subscribe", aliases=["add"], help="Cria uma inscrição de webhook"
    )
    wh_sub.add_argument("name", help="Nome da rota (usado na URL: /webhooks/<name>)")
    wh_sub.add_argument(
        "--prompt", default="", help="Template de prompt com referências de payload {dot.notation}"
    )
    wh_sub.add_argument(
        "--events", default="", help="Tipos de eventos separados por vírgula para aceitar"
    )
    wh_sub.add_argument("--description", default="", help="O que esta inscrição faz")
    wh_sub.add_argument(
        "--skills", default="", help="Nomes de skills separados por vírgula para carregar"
    )
    wh_sub.add_argument(
        "--deliver",
        default="log",
        help="Alvo de entrega: log, telegram, discord, slack, etc.",
    )
    wh_sub.add_argument(
        "--deliver-chat-id",
        default="",
        help="ID do chat de destino para entrega multiplataforma",
    )
    wh_sub.add_argument(
        "--secret", default="", help="Segredo HMAC (gerado automaticamente se omitido)"
    )
    wh_sub.add_argument(
        "--deliver-only",
        action="store_true",
        help="Pula o agente — entrega o prompt renderizado diretamente como a "
        "mensagem. Custo de LLM zero. Requer que --deliver seja um alvo real "
        "(não 'log').",
    )

    webhook_subparsers.add_parser(
        "list", aliases=["ls"], help="Lista todas as inscrições dinâmicas"
    )

    wh_rm = webhook_subparsers.add_parser(
        "remove", aliases=["rm"], help="Remove uma inscrição"
    )
    wh_rm.add_argument("name", help="Nome da inscrição para remover")

    wh_test = webhook_subparsers.add_parser(
        "test", help="Envia um POST de teste para uma rota de webhook"
    )
    wh_test.add_argument("name", help="Nome da inscrição para testar")
    wh_test.add_argument(
        "--payload", default="", help="Payload JSON para enviar (padrão: payload de teste)"
    )

    webhook_parser.set_defaults(func=_m.cmd_webhook)

    # =========================================================================
    # hooks command — shell-hook inspection and management
    # =========================================================================
    hooks_parser = subparsers.add_parser(
        "hooks",
        help="Inspeciona e gerencia hooks de script shell",
        description=(
            "Inspeciona hooks de script shell declarados em ~/.ector/config.yaml, "
            "testa-os contra payloads sintéticos e gerencia a lista de permissão "
            "de consentimento de primeiro uso em ~/.ector/shell-hooks-allowlist.json."
        ),
    )
    hooks_subparsers = hooks_parser.add_subparsers(dest="hooks_action")

    hooks_subparsers.add_parser(
        "list", aliases=["ls"],
        help="Lista hooks configurados com matcher, timeout e status de consentimento",
    )

    _hk_test = hooks_subparsers.add_parser(
        "test",
        help="Dispara cada hook correspondente a <event> contra um payload sintético",
    )
    _hk_test.add_argument(
        "event",
        help="Nome do evento do hook (ex: pre_tool_call, pre_llm_call, subagent_stop)",
    )
    _hk_test.add_argument(
        "--for-tool", dest="for_tool", default=None,
        help=(
            "Apenas dispara hooks cujo matcher corresponda a este nome de ferramenta "
            "(usado para pre_tool_call / post_tool_call)"
        ),
    )
    _hk_test.add_argument(
        "--payload-file", dest="payload_file", default=None,
        help=(
            "Caminho para um arquivo JSON cujos conteúdos são mesclados no "
            "payload sintético antes da execução"
        ),
    )

    _hk_revoke = hooks_subparsers.add_parser(
        "revoke", aliases=["remove", "rm"],
        help="Remove as entradas da lista de permissão de um comando (entra em vigor no próximo reinício)",
    )
    _hk_revoke.add_argument(
        "command",
        help="A string exata do comando para revogar (conforme declarado no config.yaml)",
    )

    hooks_subparsers.add_parser(
        "doctor",
        help=(
            "Verifica cada hook configurado: bit de execução, lista de permissão, deriva de mtime, "
            "validade do JSON e tempo de execução sintético"
        ),
    )

    hooks_parser.set_defaults(func=_m.cmd_hooks)

    # =========================================================================
    # doctor command
    # =========================================================================
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Verifica configuração e dependências",
        description="Diagnostica problemas com a configuração do Ector Agent",
    )
    doctor_parser.add_argument(
        "--fix", action="store_true", help="Tenta corrigir problemas automaticamente"
    )
    doctor_parser.set_defaults(func=_m.cmd_doctor)

    # =========================================================================
    # reset command
    # =========================================================================
    reset_parser = subparsers.add_parser(
        "reset",
        help='Formata o agente ("começar tudo do zero")',
        description="Apaga sessões, memórias, logs e o cache local do perfil "
        "(config.user.*). Use --hard para apagar a pasta ECTOR_HOME inteira "
        "(~/.ector ou perfil ativo).",
    )
    reset_parser.add_argument(
        "--hard",
        action="store_true",
        help="Remove por completo a pasta de dados do Ector (config, .env, skills, plugins, etc.)",
    )
    reset_parser.add_argument(
        "-y", "--yes", action="store_true", help="Pula o prompt de confirmação"
    )
    reset_parser.set_defaults(func=_m.cmd_reset)

    # =========================================================================
    # dump command
    # =========================================================================
    dump_parser = subparsers.add_parser(
        "dump",
        help="Resumo do ambiente para suporte e diagnóstico",
        description=(
            "Mostra versão, modelo, chaves API, gateway e configuração relevante. "
            "Use --plain para texto puro (copiar/colar ou pipes)."
        ),
    )
    dump_parser.add_argument(
        "--plain",
        action="store_true",
        help="Saída em texto puro (ideal para copiar, redirecionar ou suporte)",
    )
    dump_parser.add_argument(
        "--show-keys",
        action="store_true",
        help="Mostra prefixo/sufixo parcial das chaves API (mascarado)",
    )
    dump_parser.set_defaults(func=_m.cmd_dump)

    # =========================================================================
    # debug command
    # =========================================================================
    debug_parser = subparsers.add_parser(
        "debug",
        help="Ferramentas de diagnóstico para desenvolvedores",
        description="Várias ferramentas para depurar o Ector Agent.",
    )
    debug_sub = debug_parser.add_subparsers(dest="debug_command")

    debug_sub.add_parser("config", help="Mostra a árvore de configuração carregada")
    debug_sub.add_parser("env", help="Lista variáveis de ambiente ECTOR_* e chaves conhecidas")

    debug_tokenizer = debug_sub.add_parser("tokenizer", help="Testa a contagem de tokens")
    debug_tokenizer.add_argument("text", nargs="*", help="Texto para tokenizar")
    debug_tokenizer.add_argument("--file", help="Arquivo para tokenizar")
    debug_tokenizer.add_argument(
        "--model", default="gpt-4o", help="Codificação do modelo para usar"
    )

    debug_sub.add_parser("tools", help="Mostra ferramentas registradas e seus esquemas")

    debug_prompt = debug_sub.add_parser("prompt", help="Renderiza o prompt do sistema sem chamar o LLM")
    debug_prompt.add_argument("--skill", action="append", help="Skills para incluir")
    debug_prompt.add_argument("--workdir", help="Diretório de trabalho para contexto")

    debug_cache = debug_sub.add_parser("cache", help="Gerencia o cache de prompts/LLM")
    debug_cache.add_argument("action", choices=["clear", "stats"], help="Ação a realizar")

    debug_trace = debug_sub.add_parser("trace", help="Analisa um arquivo de trajetória (.jsonl)")
    debug_trace.add_argument("file", help="Caminho para o arquivo de trajetória")

    debug_logs = debug_sub.add_parser("logs", help="Mostra localização dos arquivos de log")
    debug_parser.set_defaults(func=_m.cmd_debug)

    # =========================================================================
    # backup command
    # =========================================================================
    backup_parser = subparsers.add_parser(
        "backup",
        help="Cria um backup das configurações e dados",
        description="Cria um arquivo .tar.gz contendo config.yaml, .env, sessões e memórias.",
    )
    backup_parser.add_argument(
        "--output", "-o", help="Caminho do arquivo de saída (padrão: ./ector-backup-DATE.tar.gz)"
    )
    backup_parser.add_argument(
        "--include-sessions",
        action="store_true",
        default=True,
        help="Inclui o banco de dados de sessões (padrão: True)",
    )
    backup_parser.add_argument(
        "--no-sessions",
        action="store_false",
        dest="include_sessions",
        help="Exclui o banco de dados de sessões",
    )
    backup_parser.set_defaults(func=_m.cmd_backup)

    # =========================================================================
    # import command
    # =========================================================================
    import_parser = subparsers.add_parser(
        "import",
        help="Restaura um backup de arquivo",
        description="Restaura configurações e dados de um arquivo criado pelo comando backup.",
    )
    import_parser.add_argument("file", help="Caminho para o arquivo .tar.gz de backup")
    import_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Sobrescreve arquivos existentes sem perguntar",
    )
    import_parser.add_argument(
        "--merge",
        action="store_true",
        help="Mescla sessões/memórias em vez de substituí-las",
    )
    import_parser.set_defaults(func=_m.cmd_import)

    # =========================================================================
    # config command
    # =========================================================================
    config_parser = subparsers.add_parser(
        "config",
        help="Visualiza e edita a configuração",
        description="Gerencia a configuração do Ector Agent",
    )
    config_subparsers = config_parser.add_subparsers(dest="config_command")

    # config show (default)
    config_subparsers.add_parser("show", help="Mostra a configuração atual")

    # config edit
    config_subparsers.add_parser("edit", help="Abre o arquivo de configuração no editor")

    # config path
    config_subparsers.add_parser("path", help="Imprime o caminho do arquivo de configuração")

    # config env-path
    config_subparsers.add_parser("env-path", help="Imprime o caminho do arquivo .env")

    # config status
    config_subparsers.add_parser(
        "status",
        help="Mostra o status da configuração (variáveis, versão e pendências)",
    )

    # config migrate
    config_subparsers.add_parser("migrate", help="Atualiza a configuração com novas opções")

    config_parser.set_defaults(func=_m.cmd_config)

    # =========================================================================
    # pairing command
    # =========================================================================
    pairing_parser = subparsers.add_parser(
        "pairing",
        help="Gerencia pareamento de DM no gateway (aprovar/revogar utilizadores)",
        description=(
            "Aprova ou revoga utilizadores que pedem acesso ao bot em plataformas "
            "de mensagens (Telegram, Discord, WhatsApp, Slack, etc.). "
            "Utilizadores desconhecidos recebem um código por DM; o dono aprova com "
            "'ector pairing approve <plataforma> <código>'."
        ),
    )
    pairing_sub = pairing_parser.add_subparsers(dest="pairing_action")

    # pairing list
    pairing_sub.add_parser(
        "list",
        help="Lista pedidos pendentes e utilizadores já aprovados",
    )

    # pairing approve
    pairing_approve = pairing_sub.add_parser(
        "approve",
        help="Aprova um código de pareamento recebido por DM",
    )
    pairing_approve.add_argument(
        "platform",
        help="Plataforma (ex.: telegram, discord, whatsapp, slack)",
    )
    pairing_approve.add_argument("code", help="Código de 8 caracteres")

    # pairing revoke
    pairing_revoke = pairing_sub.add_parser(
        "revoke",
        help="Revoga o acesso de um utilizador já aprovado",
    )
    pairing_revoke.add_argument(
        "platform",
        help="Plataforma (ex.: telegram, discord, whatsapp, slack)",
    )
    pairing_revoke.add_argument("user_id", help="ID do utilizador na plataforma")

    # pairing clear-pending
    pairing_sub.add_parser(
        "clear-pending",
        help="Remove todos os códigos de pareamento pendentes",
    )

    def cmd_pairing(args):
        from ector_cli.pairing import pairing_command

        pairing_command(args)

    pairing_parser.set_defaults(func=cmd_pairing)

    # =========================================================================
    # skills command
    # =========================================================================
    skills_parser = subparsers.add_parser(
        "skills",
        help="Gerencia skills (habilidades) do agente",
        description=(
            "Gerencia skills que dão ao seu agente habilidades específicas.\n\n"
            "Skills são conjuntos de prompts, ferramentas e regras que podem ser "
            "carregados sob demanda ou permanentemente."
        ),
    )
    skills_sub = skills_parser.add_subparsers(dest="skills_action")

    _skills_source_choices = [
        "all",
        "hub",
        "official",
        "builtin",
        "skills-sh",
        "well-known",
        "github",
        "clawhub",
        "claude-marketplace",
        "lobehub",
    ]

    # skills browse
    skills_browse = skills_sub.add_parser(
        "browse", help="Navega skills disponíveis nos registros"
    )
    skills_browse.add_argument(
        "--page", type=int, default=1, help="Número da página (padrão: 1)"
    )
    skills_browse.add_argument(
        "--size", type=int, default=20, help="Itens por página (padrão: 20, máx: 100)"
    )
    skills_browse.add_argument(
        "--source",
        choices=_skills_source_choices,
        default="all",
        help="Filtra por registro (padrão: all). Use hub para skills oficiais do Ector Hub",
    )

    # skills search
    skills_search = skills_sub.add_parser(
        "search", help="Pesquisa skills nos registros"
    )
    skills_search.add_argument(
        "query", help="Termo de busca (ex: onboarding, web scraping)"
    )
    skills_search.add_argument(
        "--source",
        choices=_skills_source_choices,
        default="all",
        help="Filtra por registro (padrão: all). Use hub para skills oficiais do Ector Hub",
    )
    skills_search.add_argument(
        "--limit", type=int, default=10, help="Máximo de resultados (padrão: 10)"
    )

    # skills list
    skills_list = skills_sub.add_parser(
        "list", aliases=["ls"], help="Lista skills instaladas neste dispositivo"
    )
    skills_list.add_argument(
        "--source",
        choices=["all", "hub", "local"],
        default="all",
        help="Filtra por origem: all (padrão), hub ou local",
    )
    skills_list.add_argument(
        "--enabled-only",
        action="store_true",
        help="Mostra apenas skills ativas (não desabilitadas no config)",
    )

    # skills create
    skills_create = skills_sub.add_parser(
        "create", help="Cria uma skill local com template SKILL.md"
    )
    skills_create.add_argument(
        "name", nargs="?", help="Nome da skill (ex.: deploy-nextjs)"
    )
    skills_create.add_argument("--category", help="Categoria (subdir opcional)")
    skills_create.add_argument(
        "--description", help="Descrição curta no frontmatter YAML"
    )
    skills_create.add_argument(
        "--no-edit",
        action="store_true",
        help="Não abrir $EDITOR — usar template padrão",
    )
    skills_create.add_argument(
        "--yes", "-y", action="store_true", help="Pular confirmação"
    )

    # skills install
    skills_install = skills_sub.add_parser("install", help="Instala uma skill")
    skills_install.add_argument(
        "source",
        help="Caminho local, URL ou nome da skill no Hub (ex: ector-hub-onboarding)",
    )
    skills_install.add_argument("--name", help="Nome personalizado opcional para a skill")
    skills_install.add_argument(
        "--force", action="store_true", help="Sobrescreve se já existir"
    )
    skills_install.add_argument(
        "--yes", "-y", action="store_true", help="Pula confirmações"
    )

    skills_inspect = skills_sub.add_parser(
        "inspect", help="Pré-visualiza uma skill sem instalar"
    )
    skills_inspect.add_argument("identifier", help="Identificador da skill")

    skills_sub.add_parser(
        "sync",
        aliases=["library-sync", "sync-cloud"],
        help="Sincroniza a biblioteca Ector Hub para este dispositivo",
    )

    skills_remove = skills_sub.add_parser(
        "remove",
        aliases=["library-remove", "library-rm"],
        help="Remove da biblioteca na nuvem e desinstala localmente",
    )
    skills_remove.add_argument(
        "identifier",
        metavar="slug",
        help="Slug da skill (ex.: ector-hub-onboarding)",
    )

    skills_update = skills_sub.add_parser(
        "update",
        aliases=["check"],
        help="Verifica e aplica atualizações de skills instaladas via hub",
    )
    skills_update.add_argument(
        "name",
        nargs="?",
        help="Skill específica (padrão: todas). Sem atualizações, mostra o status.",
    )

    skills_audit = skills_sub.add_parser(
        "audit", help="Re-analisa skills instaladas via hub"
    )
    skills_audit.add_argument(
        "name", nargs="?", help="Skill específica para analisar (padrão: todas)"
    )

    skills_uninstall = skills_sub.add_parser(
        "uninstall", help="Remove uma skill instalada via hub"
    )
    skills_uninstall.add_argument("name", help="Nome da skill para remover")

    skills_publish = skills_sub.add_parser(
        "publish", help="Publica uma skill em um registro"
    )
    skills_publish.add_argument("skill_path", help="Caminho para o diretório da skill")
    skills_publish.add_argument(
        "--to", default="github", choices=["github", "clawhub"], help="Registro de destino"
    )
    skills_publish.add_argument(
        "--repo", default="", help="Repositório GitHub de destino (ex: openai/skills)"
    )

    skills_snapshot = skills_sub.add_parser(
        "snapshot", help="Exporta/importa configurações de skill"
    )
    snapshot_subparsers = skills_snapshot.add_subparsers(dest="snapshot_action")
    snap_export = snapshot_subparsers.add_parser(
        "export", help="Exporta skills instaladas para um arquivo"
    )
    snap_export.add_argument("output", help="Caminho do arquivo JSON de saída (use - para stdout)")
    snap_import = snapshot_subparsers.add_parser(
        "import", help="Importa e instala skills de um arquivo"
    )
    snap_import.add_argument("input", help="Caminho do arquivo JSON de entrada")
    snap_import.add_argument(
        "--force", action="store_true", help="Força a instalação apesar do veredito de cautela"
    )

    skills_tap = skills_sub.add_parser("tap", help="Gerencia fontes de skill")
    tap_subparsers = skills_tap.add_subparsers(dest="tap_action")
    tap_subparsers.add_parser("list", help="Lista taps configurados")
    tap_add = tap_subparsers.add_parser("add", help="Adiciona um repositório GitHub como fonte de skill")
    tap_add.add_argument("repo", help="Repositório GitHub (ex: proprietário/repo)")
    tap_rm = tap_subparsers.add_parser("remove", help="Remove um tap")
    tap_rm.add_argument("name", help="Nome do tap a ser removido")

    # config sub-action: interactive enable/disable
    skills_sub.add_parser(
        "config",
        help="Configuração interativa de skills — habilita/desabilita skills individuais",
    )

    def cmd_skills(args):
        # Route 'config' action to skills_config module
        if getattr(args, "skills_action", None) == "config":
            _m._require_tty("skills config")
            from ector_cli.skills_config import skills_command as skills_config_command

            skills_config_command(args)
        else:
            from ector_cli.skills_hub import skills_command

            skills_command(args)

    skills_parser.set_defaults(func=cmd_skills)

    # =========================================================================
    # plugins command
    # =========================================================================
    plugins_parser = subparsers.add_parser(
        "plugins",
        help="Gerencia plugins — instala, atualiza, remove, lista",
        description="Instala plugins de repositórios Git, atualiza, remove ou lista-os.",
    )
    plugins_subparsers = plugins_parser.add_subparsers(dest="plugins_action")

    plugins_install = plugins_subparsers.add_parser(
        "install",
        help="Instala plugin de repositório Git em ~/.ector/plugins/",
        description=(
            "Clona um repositório Git para <ECTOR_HOME>/plugins/<nome>/ "
            "(padrão ~/.ector/plugins/). Atalho owner/repo aponta para GitHub."
        ),
    )
    plugins_install.add_argument(
        "identifier",
        help="URL Git ou owner/repo no GitHub (ex.: ectoragent/meu-plugin)",
    )
    plugins_install.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Remove o plugin existente e reinstala",
    )
    _install_enable_group = plugins_install.add_mutually_exclusive_group()
    _install_enable_group.add_argument(
        "--enable",
        action="store_true",
        help="Habilita automaticamente o plugin após a instalação (pula prompt de confirmação)",
    )
    _install_enable_group.add_argument(
        "--no-enable",
        action="store_true",
        help="Instala desabilitado (pula prompt de confirmação); habilite mais tarde com `ector plugins enable <name>`",
    )

    plugins_update = plugins_subparsers.add_parser(
        "update", help="Pull latest changes for an installed plugin"
    )
    plugins_update.add_argument("name", help="Nome do plugin para atualizar")

    plugins_remove = plugins_subparsers.add_parser(
        "remove", aliases=["rm", "uninstall"], help="Remove an installed plugin"
    )
    plugins_remove.add_argument("name", help="Nome do diretório do plugin para remover")

    plugins_subparsers.add_parser("list", aliases=["ls"], help="Lista plugins instalados")

    plugins_enable = plugins_subparsers.add_parser(
        "enable", help="Enable a disabled plugin"
    )
    plugins_enable.add_argument("name", help="Nome do plugin para habilitar")

    plugins_disable = plugins_subparsers.add_parser(
        "disable", help="Disable a plugin without removing it"
    )
    plugins_disable.add_argument("name", help="Nome do plugin para desabilitar")

    def cmd_plugins(args):
        from ector_cli.plugins_cmd import plugins_command

        plugins_command(args)

    plugins_parser.set_defaults(func=cmd_plugins)

    # =========================================================================
    # Plugin CLI commands — dynamically registered by memory/general plugins.
    # Plugins provide a register_cli(subparser) function that builds their
    # own argparse tree.  No hardcoded plugin commands in main.py.
    # =========================================================================
    try:
        from plugins.memory import discover_plugin_cli_commands

        for cmd_info in discover_plugin_cli_commands():
            plugin_parser = subparsers.add_parser(
                cmd_info["name"],
                help=cmd_info["help"],
                description=cmd_info.get("description", ""),
                formatter_class=__import__("argparse").RawDescriptionHelpFormatter,
            )
            cmd_info["setup_fn"](plugin_parser)
    except Exception as _exc:
        logging.getLogger(__name__).debug("Plugin CLI discovery failed: %s", _exc)

    # =========================================================================
    # memory command
    # =========================================================================
    memory_parser = subparsers.add_parser(
        "memory",
        help="Configura e gere memória (nativa + plugins externos)",
        description=(
            "A memória nativa (MEMORY.md / USER.md) está sempre ativa.\n"
            "Opcionalmente, escolha um plugin externo em memory.provider.\n\n"
            "Subcomandos: status (padrão), setup, off, reset."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
    Exemplos:
    ector memory                 Status (nativo + provedor ativo)
    ector memory setup           Escolher e configurar plugin
    ector memory off             Só memória nativa
    ector memory reset           Apagar MEMORY.md / USER.md
    ector memory reset --yes     Sem confirmação interativa
    """,
    )
    memory_sub = memory_parser.add_subparsers(dest="memory_command")
    memory_sub.add_parser(
        "setup", help="Seleção e configuração interativa de provedores"
    )
    memory_sub.add_parser("status", help="Mostra a configuração atual do plugin de memória")
    memory_sub.add_parser("off", help="Desabilita o provedor externo (apenas embutido)")
    _reset_parser = memory_sub.add_parser(
        "reset",
        help="Apaga toda a memória embutida (MEMORY.md e USER.md)",
    )
    _reset_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Pula o prompt de confirmação",
    )
    _reset_parser.add_argument(
        "--target",
        choices=["all", "memory", "user"],
        default="all",
        help="Qual armazenamento redefinir: 'all' (padrão), 'memory' ou 'user'",
    )

    def cmd_memory(args):
        from ector_cli.memory_setup import memory_command

        memory_command(args)

    memory_parser.set_defaults(func=cmd_memory)

    # =========================================================================
    # tools command
    # =========================================================================
    tools_parser = subparsers.add_parser(
        "tools",
        help="Configura quais ferramentas estão habilitadas por plataforma",
        description=(
            "Habilita, desabilita ou lista ferramentas para CLI, Telegram, Discord, etc.\n\n"
            "Conjuntos de ferramentas integrados usam nomes simples (ex: web, memory).\n"
            "Ferramentas MCP usam a notação servidor:ferramenta (ex: github:create_issue).\n\n"
            "Execute 'ector tools' sem subcomando para a interface de configuração interativa."
        ),
    )
    tools_parser.add_argument(
        "--summary",
        action="store_true",
        help="Imprime um resumo das ferramentas habilitadas por plataforma e sai",
    )
    tools_sub = tools_parser.add_subparsers(dest="tools_action")

    # ector tools list [--platform cli]
    tools_list_p = tools_sub.add_parser(
        "list",
        help="Mostra todas as ferramentas e seu status (habilitada/desabilitada)",
    )
    tools_list_p.add_argument(
        "--platform",
        default="cli",
        help="Plataforma para mostrar (padrão: cli)",
    )

    # ector tools disable <name...> [--platform cli]
    tools_disable_p = tools_sub.add_parser(
        "disable",
        help="Desabilita conjuntos de ferramentas ou ferramentas MCP",
    )
    tools_disable_p.add_argument(
        "names",
        nargs="+",
        metavar="NOME",
        help="Nome do conjunto de ferramentas (ex: web) ou ferramenta MCP na forma servidor:ferramenta",
    )
    tools_disable_p.add_argument(
        "--platform",
        default="cli",
        help="Plataforma para aplicar (padrão: cli)",
    )

    # ector tools enable <name...> [--platform cli]
    tools_enable_p = tools_sub.add_parser(
        "enable",
        help="Habilita conjuntos de ferramentas ou ferramentas MCP",
    )
    tools_enable_p.add_argument(
        "names",
        nargs="+",
        metavar="NOME",
        help="Nome do conjunto de ferramentas ou ferramenta MCP na forma servidor:ferramenta",
    )
    tools_enable_p.add_argument(
        "--platform",
        default="cli",
        help="Plataforma para aplicar (padrão: cli)",
    )

    def cmd_tools(args):
        action = getattr(args, "tools_action", None)
        if action in ("list", "disable", "enable"):
            from ector_cli.tools_config import tools_disable_enable_command

            tools_disable_enable_command(args)
        else:
            _m._require_tty("tools")
            from ector_cli.tools_config import tools_command

            tools_command(args)

    tools_parser.set_defaults(func=cmd_tools)
    # =========================================================================
    # mcp command — manage MCP server connections
    # =========================================================================
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Gerencia servidores MCP e executa o Ector como um servidor MCP",
        description=(
            "Gerencia conexões de servidores MCP e executa o Ector como um servidor MCP.\n\n"
            "Servidores MCP fornecem ferramentas adicionais através do Model Context Protocol.\n"
            "Use 'ector mcp add' para conectar-se a um novo servidor, ou\n"
            "'ector mcp serve' para expor conversas do Ector via MCP."
        ),
    )
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_action")

    mcp_serve_p = mcp_sub.add_parser(
        "serve",
        help="Executa o Ector como um servidor MCP (expõe conversas para outros agentes)",
    )
    mcp_serve_p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Habilita log detalhado no stderr",
    )
    _add_accept_hooks_flag(mcp_serve_p)

    mcp_add_p = mcp_sub.add_parser(
        "add", help="Adiciona um servidor MCP (instalação com descoberta primeiro)"
    )
    mcp_add_p.add_argument("name", help="Nome do servidor (usado como chave de configuração)")
    mcp_add_p.add_argument("--url", help="URL do endpoint HTTP/SSE")
    mcp_add_p.add_argument("--command", help="Comando stdio (ex: npx)")
    mcp_add_p.add_argument(
        "--args", nargs="*", default=[], help="Argumentos para o comando stdio"
    )
    mcp_add_p.add_argument("--auth", choices=["oauth", "header"], help="Método de autenticação")
    mcp_add_p.add_argument("--preset", help="Nome de preset MCP conhecido")
    mcp_add_p.add_argument(
        "--env",
        nargs="*",
        default=[],
        help="Variáveis de ambiente para servidores stdio (CHAVE=VALOR)",
    )

    mcp_rm_p = mcp_sub.add_parser("remove", aliases=["rm"], help="Remove um servidor MCP")
    mcp_rm_p.add_argument("name", help="Nome do servidor para remover")

    mcp_sub.add_parser("list", aliases=["ls"], help="Lista servidores MCP configurados")

    mcp_test_p = mcp_sub.add_parser("test", help="Testa a conexão com o servidor MCP")
    mcp_test_p.add_argument("name", help="Nome do servidor para testar")

    mcp_cfg_p = mcp_sub.add_parser(
        "configure", aliases=["config"], help="Alterna a seleção de ferramentas"
    )
    mcp_cfg_p.add_argument("name", help="Nome do servidor para configurar")

    mcp_login_p = mcp_sub.add_parser(
        "login",
        help="Força a reautenticação para um servidor MCP baseado em OAuth",
    )
    mcp_login_p.add_argument("name", help="Nome do servidor para reautenticar")

    _add_accept_hooks_flag(mcp_parser)

    def cmd_mcp(args):
        from ector_cli.mcp_config import mcp_command

        mcp_command(args)

    mcp_parser.set_defaults(func=cmd_mcp)

    # =========================================================================
    # sessions command
    # =========================================================================
    sessions_parser = subparsers.add_parser(
        "sessions",
        help="Gerencia o histórico de sessões (listar, renomear, exportar, remover, excluir)",
        description="Visualiza e gerencia o armazenamento de sessões SQLite",
    )
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_action")

    sessions_list = sessions_subparsers.add_parser("list", help="Lista sessões recentes")
    sessions_list.add_argument(
        "--source", help="Filtrar por origem (cli, telegram, discord, etc.)"
    )
    sessions_list.add_argument(
        "--limit", type=int, default=20, help="Máximo de sessões para mostrar"
    )

    sessions_export = sessions_subparsers.add_parser(
        "export", help="Exporta sessões para um arquivo JSONL"
    )
    sessions_export.add_argument(
        "output", help="Caminho do arquivo JSONL de saída (use - para stdout)"
    )
    sessions_export.add_argument("--source", help="Filtrar por origem")
    sessions_export.add_argument("--session-id", help="Exporta uma sessão específica")

    sessions_delete = sessions_subparsers.add_parser(
        "delete", help="Exclui uma sessão específica"
    )
    sessions_delete.add_argument("session_id", help="ID da sessão para excluir")
    sessions_delete.add_argument(
        "--yes", "-y", action="store_true", help="Pula a confirmação"
    )

    sessions_prune = sessions_subparsers.add_parser("prune", help="Exclui sessões antigas")
    sessions_prune.add_argument(
        "--older-than",
        type=int,
        default=90,
        help="Exclui sessões anteriores a N dias (padrão: 90)",
    )
    sessions_prune.add_argument("--source", help="Apenas remove sessões desta origem")
    sessions_prune.add_argument(
        "--yes", "-y", action="store_true", help="Pula a confirmação"
    )

    sessions_subparsers.add_parser("stats", help="Mostra estatísticas do armazenamento de sessões")

    sessions_rename = sessions_subparsers.add_parser(
        "rename", help="Define ou altera o título de uma sessão"
    )
    sessions_rename.add_argument("session_id", help="ID da sessão para renomear")
    sessions_rename.add_argument("title", nargs="+", help="Novo título para a sessão")

    sessions_browse = sessions_subparsers.add_parser(
        "browse",
        help="Seletor interativo de sessões — navegue, pesquise e retome sessões",
    )
    sessions_browse.add_argument(
        "--source", help="Filtrar por origem (cli, telegram, discord, etc.)"
    )
    sessions_browse.add_argument(
        "--limit", type=int, default=500, help="Máximo de sessões para carregar (padrão: 500)"
    )

    def _confirm_prompt(prompt: str) -> bool:
        """Prompt for y/N confirmation, safe against non-TTY environments."""
        try:
            return input(prompt).strip().lower() in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    def cmd_sessions(args):
        import json as _json

        try:
            from ector_state import SessionDB

            db = SessionDB()
        except Exception as e:
            print(f"Erro: Não foi possível abrir o banco de dados de sessões: {e}")
            return

        action = args.sessions_action

        # Hide third-party tool sessions by default, but honour explicit --source
        _source = getattr(args, "source", None)
        _exclude = None if _source else ["tool"]

        if action == "list":
            sessions = db.list_sessions_rich(
                source=args.source, exclude_sources=_exclude, limit=args.limit
            )
            from ector_cli.sessions_cmd import print_sessions_list

            print_sessions_list(
                sessions,
                source=args.source,
                limit=args.limit,
                db_path=db.db_path,
            )

        elif action == "export":
            if args.session_id:
                resolved_session_id = db.resolve_session_id(args.session_id)
                if not resolved_session_id:
                    print(f"Sessão '{args.session_id}' não encontrada.")
                    return
                data = db.export_session(resolved_session_id)
                if not data:
                    print(f"Sessão '{args.session_id}' não encontrada.")
                    return
                line = _json.dumps(data, ensure_ascii=False) + "\n"
                if args.output == "-":

                    sys.stdout.write(line)
                else:
                    with open(args.output, "w", encoding="utf-8") as f:
                        f.write(line)
                    print(f"Exportou 1 sessão para {args.output}")
            else:
                sessions = db.export_all(source=args.source)
                if args.output == "-":

                    for s in sessions:
                        sys.stdout.write(_json.dumps(s, ensure_ascii=False) + "\n")
                else:
                    with open(args.output, "w", encoding="utf-8") as f:
                        for s in sessions:
                            f.write(_json.dumps(s, ensure_ascii=False) + "\n")
                    print(f"Exportou {len(sessions)} sessões para {args.output}")

        elif action == "delete":
            resolved_session_id = db.resolve_session_id(args.session_id)
            if not resolved_session_id:
                print(f"Sessão '{args.session_id}' não encontrada.")
                return
            if not args.yes:
                if not _confirm_prompt(
                    f"Excluir sessão '{resolved_session_id}' e todas as suas mensagens? (s/n) "
                ):
                    print("Cancelado.")
                    return
            sessions_dir = get_ector_home() / "sessions"
            if db.delete_session(resolved_session_id, sessions_dir=sessions_dir):
                try:
                    from tools.process_registry import process_registry

                    killed = process_registry.kill_all_for_session_key(
                        resolved_session_id
                    )
                    if killed:
                        print(f"  ✔ {killed} processo(s) em segundo plano encerrado(s).")
                except Exception:
                    pass
                print(f"Sessão '{resolved_session_id}' excluída.")
            else:
                print(f"Sessão '{args.session_id}' não encontrada.")

        elif action == "prune":
            days = args.older_than
            source_msg = f" de '{args.source}'" if args.source else ""
            if not args.yes:
                if not _confirm_prompt(
                    f"Excluir todas as sessões finalizadas anteriores a {days} dias{source_msg}? (s/n) "
                ):
                    print("Cancelado.")
                    return
            sessions_dir = get_ector_home() / "sessions"
            count = db.prune_sessions(older_than_days=days, source=args.source,
                                      sessions_dir=sessions_dir)
            print(f"{count} sessão(ões) removida(s).")

        elif action == "rename":
            resolved_session_id = db.resolve_session_id(args.session_id)
            if not resolved_session_id:
                print(f"Sessão '{args.session_id}' não encontrada.")
                return
            title = " ".join(args.title)
            try:
                if db.set_session_title(resolved_session_id, title, user_set=True):
                    print(f"Sessão '{resolved_session_id}' renomeada para: {title}")
                else:
                    print(f"Sessão '{args.session_id}' não encontrada.")
            except ValueError as e:
                print(f"Erro: {e}")

        elif action == "browse":
            limit = getattr(args, "limit", 500) or 500
            source = getattr(args, "source", None)
            _browse_exclude = None if source else ["tool"]
            sessions = db.list_sessions_rich(
                source=source, exclude_sources=_browse_exclude, limit=limit
            )
            db.close()
            if not sessions:
                print("Nenhuma sessão encontrada.")
                return

            selected_id = _m._session_browse_picker(sessions)
            if not selected_id:
                print("Cancelado.")
                return

            # Abre o painel web na sessão escolhida
            print(f"Retomando sessão: {selected_id}")
            from ector_cli.main import launch_dashboard_with_resume

            launch_dashboard_with_resume(selected_id)
            return

        elif action == "stats":
            total = db.session_count()
            msgs = db.message_count()
            print(f"Total de sessões: {total}")
            print(f"Total de mensagens: {msgs}")
            for src in ["cli", "telegram", "discord", "whatsapp", "slack"]:
                c = db.session_count(source=src)
                if c > 0:
                    print(f"  {src}: {c} sessões")
            db_path = db.db_path
            if db_path.exists():
                size_mb = os.path.getsize(db_path) / (1024 * 1024)
                print(f"Tamanho do banco de dados: {size_mb:.1f} MB")

        else:
            sessions_parser.print_help()

        db.close()

    sessions_parser.set_defaults(func=cmd_sessions)

    # =========================================================================
    # stats command
    # =========================================================================
    stats_parser = subparsers.add_parser(
        "stats",
        aliases=["insights"],
        help="Mostra estatísticas de uso e analítica",
        description="Analisa o histórico de sessões para mostrar uso de tokens, custos, padrões de ferramentas e tendências de atividade",
    )
    stats_parser.add_argument(
        "--days", type=int, default=30, help="Número de dias para analisar (padrão: 30)"
    )
    stats_parser.add_argument(
        "--source", help="Filtrar por plataforma (cli, telegram, discord, etc.)"
    )

    def cmd_stats(args):
        try:
            from ector_state import SessionDB
            from agent.stats import StatsEngine
            from ector_cli.stats_cmd import print_stats_report

            db = SessionDB()
            engine = StatsEngine(db)
            report = engine.generate(days=args.days, source=args.source)
            print_stats_report(report)
            db.close()
        except Exception as e:
            print(f"Erro ao gerar estatísticas: {e}")

    stats_parser.set_defaults(func=cmd_stats)

    # =========================================================================
    # version command
    # =========================================================================
    version_parser = subparsers.add_parser("version", help="Mostra informações da versão")
    version_parser.set_defaults(func=_m.cmd_version)

    # =========================================================================
    # update command
    # =========================================================================
    update_parser = subparsers.add_parser(
        "update",
        help="Atualiza o Ector Agent (git pull + dependências via instalador)",
        description=(
            "Atualiza a instalação git do Ector Agent a partir de "
            "ector-agent-release (fetch, pull, venv, Node/TUI, skills).\n\n"
            "Equivalente a executar o instalador com --skip-setup no diretório "
            "de código ativo (~/.ector/agent, ~/.ector/ector-agent, ou checkout dev)."
        ),
    )
    update_parser.add_argument(
        "--check",
        action="store_true",
        help="Apenas verifica se há atualizações disponíveis (não instala)",
    )
    update_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Pula o backup zip de ECTOR_HOME antes da atualização",
    )
    update_parser.set_defaults(func=_m.cmd_update)

    # =========================================================================
    # uninstall command
    # =========================================================================
    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Desinstala o Ector Agent",
        description="Remove o Ector Agent do seu sistema. Pode manter configurações/dados para reinstalação.",
    )
    uninstall_parser.add_argument(
        "--full",
        action="store_true",
        help="Desinstalação completa - remove tudo, incluindo configurações e dados",
    )
    uninstall_parser.add_argument(
        "--yes", "-y", action="store_true", help="Pula prompts de confirmação"
    )
    uninstall_parser.set_defaults(func=_m.cmd_uninstall)

    # =========================================================================
    # acp command
    # =========================================================================
    acp_parser = subparsers.add_parser(
        "acp",
        help="Executa o Ector Agent como um servidor ACP (Agent Client Protocol)",
        description="Inicia o Ector Agent no modo ACP para integração com editores (VS Code, Zed, JetBrains)",
    )
    _add_accept_hooks_flag(acp_parser)

    def cmd_acp(args):
        """Launch Ector Agent as an ACP server."""
        try:
            from acp_adapter.entry import main as acp_main

            acp_main()
        except ImportError:
            print("Dependências ACP não instaladas.")
            print("Instale-as com:  pip install -e '.[acp]'")
            sys.exit(1)

    acp_parser.set_defaults(func=cmd_acp)

    # =========================================================================
    # profile command
    # =========================================================================
    profile_parser = subparsers.add_parser(
        "profile",
        help="Gerencia perfis — múltiplas instâncias isoladas do Ector",
    )
    profile_subparsers = profile_parser.add_subparsers(dest="profile_action")

    profile_subparsers.add_parser("list", help="Lista todos os perfis")
    profile_use = profile_subparsers.add_parser(
        "use", help="Define o perfil padrão persistente"
    )
    profile_use.add_argument("profile_name", help="Nome do perfil (ou 'default')")

    profile_create = profile_subparsers.add_parser(
        "create", help="Cria um novo perfil"
    )
    profile_create.add_argument(
        "profile_name", help="Nome do perfil (minúsculas, alfanumérico)"
    )
    profile_create.add_argument(
        "--clone",
        action="store_true",
        help="Copia config.yaml, .env, SOUL.md do perfil ativo",
    )
    profile_create.add_argument(
        "--clone-all",
        action="store_true",
        help="Cópia completa do perfil ativo (todo o estado)",
    )
    profile_create.add_argument(
        "--clone-from",
        metavar="SOURCE",
        help="Perfil de origem para clonar (padrão: ativo)",
    )
    profile_create.add_argument(
        "--no-alias", action="store_true", help="Pula a criação do script wrapper"
    )

    profile_delete = profile_subparsers.add_parser("delete", help="Exclui um perfil")
    profile_delete.add_argument("profile_name", help="Perfil a ser excluído")
    profile_delete.add_argument(
        "-y", "--yes", action="store_true", help="Pula o aviso de confirmação"
    )

    profile_show = profile_subparsers.add_parser("show", help="Mostra detalhes do perfil")
    profile_show.add_argument("profile_name", help="Perfil a ser mostrado")

    profile_alias = profile_subparsers.add_parser(
        "alias", help="Gerencia scripts wrapper"
    )
    profile_alias.add_argument("profile_name", help="Nome do perfil")
    profile_alias.add_argument(
        "--remove", action="store_true", help="Remove o script wrapper"
    )
    profile_alias.add_argument(
        "--name",
        dest="alias_name",
        metavar="NAME",
        help="Nome personalizado para o alias (padrão: nome do perfil)",
    )

    profile_rename = profile_subparsers.add_parser("rename", help="Renomeia um perfil")
    profile_rename.add_argument("old_name", help="Nome atual do perfil")
    profile_rename.add_argument("new_name", help="Novo nome do perfil")

    profile_export = profile_subparsers.add_parser(
        "export", help="Exporta um perfil para um arquivo"
    )
    profile_export.add_argument("profile_name", help="Perfil a ser exportado")
    profile_export.add_argument(
        "-o", "--output", default=None, help="Arquivo de saída (padrão: <nome>.tar.gz)"
    )

    profile_import = profile_subparsers.add_parser(
        "import", help="Importa um perfil de um arquivo"
    )
    profile_import.add_argument("archive", help="Caminho para o arquivo .tar.gz")
    profile_import.add_argument(
        "--name",
        dest="import_name",
        metavar="NAME",
        help="Nome do perfil (padrão: inferido do arquivo)",
    )

    profile_parser.set_defaults(func=_m.cmd_profile)

    # =========================================================================
    # logs command
    # =========================================================================
    logs_parser = subparsers.add_parser(
        "logs",
        help="Visualiza e filtra arquivos de log do Ector",
        description="Visualiza, tail (acompanha) e filtra agent.log / errors.log / gateway.log",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
    Exemplos:
    ector logs                    Mostra as últimas 50 linhas de agent.log
    ector logs -f                 Acompanha agent.log em tempo real
    ector logs errors             Mostra as últimas 50 linhas de errors.log
    ector logs gateway -n 100     Mostra as últimas 100 linhas de gateway.log
    ector logs --level WARNING    Mostra apenas WARNING e acima
    ector logs --session abc123   Filtra pelo ID da sessão
    ector logs --component tools  Mostra apenas linhas relacionadas a ferramentas
    ector logs --since 1h         Linhas da última hora
    ector logs --since 30m -f     Acompanha, começando de 30 min atrás
    ector logs list               Lista arquivos de log disponíveis com tamanhos
    ector logs clear              Esvazia todos os arquivos .log
    ector logs clear agent        Esvazia apenas agent.log
    """,
    )
    logs_parser.add_argument(
        "log_name",
        nargs="?",
        default="agent",
        help="Log para visualizar: agent (padrão), errors, gateway, list ou clear",
    )
    logs_parser.add_argument(
        "clear_target",
        nargs="?",
        default=None,
        help="Com clear: agent, errors ou gateway (omitir = todos os .log)",
    )
    logs_parser.add_argument(
        "-n",
        "--lines",
        type=int,
        default=50,
        help="Número de linhas para mostrar (padrão: 50)",
    )
    logs_parser.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="Acompanha o log em tempo real (como tail -f)",
    )
    logs_parser.add_argument(
        "--level",
        metavar="LEVEL",
        help="Nível mínimo de log para mostrar (DEBUG, INFO, WARNING, ERROR)",
    )
    logs_parser.add_argument(
        "--session",
        metavar="ID",
        help="Filtra linhas contendo este ID de sessão",
    )
    logs_parser.add_argument(
        "--since",
        metavar="TIME",
        help="Mostra linhas desde TIME atrás (ex: 1h, 30m, 2d)",
    )
    logs_parser.add_argument(
        "--component",
        metavar="NAME",
        help="Filtra por componente: gateway, agent, tools, cli, cron",
    )
    logs_parser.set_defaults(func=_m.cmd_logs)
    return parser, subparsers
