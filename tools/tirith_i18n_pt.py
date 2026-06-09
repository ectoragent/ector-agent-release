"""Tradução pt-BR de achados do scanner Tirith para prompts de aprovação."""

from __future__ import annotations

import re

# Títulos estáticos retornados pelo Tirith (title: "...")
_TIRITH_TITLE_PT: dict[str, str] = {
    "ANSI escape sequences in pasted content": "Sequências de escape ANSI no conteúdo colado",
    "Archive extraction to sensitive path": "Extração de arquivo para caminho sensível",
    "Base64 decode piped to interpreter": "Decodificação Base64 canalizada para interpretador",
    "Bidirectional control characters detected": "Caracteres de controle bidirecionais detectados",
    "Clipboard HTML contains hidden content": "HTML da área de transferência com conteúdo oculto",
    "Clipboard HTML contains more text than visible paste": (
        "HTML da área de transferência com mais texto que o colado visível"
    ),
    "Confusable Unicode characters in text": "Caracteres Unicode confusíveis no texto",
    "Confusable domain detected": "Domínio confusível detectado",
    "Control characters in pasted content": "Caracteres de controle no conteúdo colado",
    "Data exfiltration via curl upload": "Exfiltração de dados via upload curl",
    "Data exfiltration via wget upload": "Exfiltração de dados via upload wget",
    "Docker image from untrusted registry": "Imagem Docker de registro não confiável",
    "Docker remote privileged escalation detected": "Escalação privilegiada remota no Docker detectada",
    "Domain similar to known domain": "Domínio semelhante a um domínio conhecido",
    "Domain-like userinfo in URL": "Userinfo com aparência de domínio na URL",
    "Dotfile overwrite detected": "Sobrescrita de dotfile detectada",
    "Ethereum address found in URL": "Endereço Ethereum encontrado na URL",
    "Hangul Filler characters detected": "Caracteres Hangul Filler detectados",
    "Hidden multiline content detected": "Conteúdo multilinha oculto detectado",
    "Inline base64 decode-execute": "Decodificação Base64 inline com execução",
    "Insecure TLS flag detected": "Flag TLS insegura detectada",
    "Invalid characters in hostname": "Caracteres inválidos no hostname",
    "Invisible math operator characters detected": "Operadores matemáticos invisíveis detectados",
    "Invisible whitespace characters detected": "Espaços em branco invisíveis detectados",
    "Lookalike TLD detected": "TLD parecido detectado",
    "Mixed scripts in hostname label": "Scripts mistos no rótulo do hostname",
    "Multiple credential files accessed": "Vários arquivos de credenciais acessados",
    "No supply-chain audit configured": "Auditoria de cadeia de suprimentos não configurada",
    "Non-ASCII characters in hostname": "Caracteres não ASCII no hostname",
    "Non-standard port on known domain": "Porta não padrão em domínio conhecido",
    "OCR-confusable domain detected": "Domínio confusível por OCR detectado",
    "Plain HTTP URL in execution context": "URL HTTP sem TLS em contexto de execução",
    "Possible git repository typosquat": "Possível typosquat de repositório git",
    "Pipe to interpreter": "Canalização para interpretador",
    "PowerShell encoded command": "Comando PowerShell codificado",
    "Process memory access detected": "Acesso à memória de processo detectado",
    "Punycode domain detected": "Domínio punycode detectado",
    "Python package from non-PyPI source": "Pacote Python de fonte fora do PyPI",
    "Schemeless URL in sink context": "URL sem esquema em contexto de execução",
    "Shortened URL detected": "URL encurtada detectada",
    "Suspicious URL": "URL suspeita",
    "Trailing dot or whitespace in hostname": "Ponto final ou espaço no hostname",
    "URL uses raw IP address": "URL usa endereço IP bruto",
    "URL uses raw IPv6 address": "URL usa endereço IPv6 bruto",
    "Unicode Tags (hidden ASCII) detected": "Tags Unicode (ASCII oculto) detectadas",
    "Variation selector characters detected": "Seletores de variação Unicode detectados",
    "Web3 RPC endpoint detected": "Endpoint RPC Web3 detectado",
    "Zero-width characters detected": "Caracteres de largura zero detectados",
    "npm package from non-registry source": "Pacote npm de fonte fora do registro",
    "Download piped to interpreter": "Download canalizado para interpretador",
}

# rule_id → título base (quando o JSON traz rule_id mas título vazio/desatualizado)
_TIRITH_RULE_ID_TITLE_PT: dict[str, str] = {
    "pipe_to_interpreter": "Canalização para interpretador",
    "curl_pipe_shell": "curl canalizado para shell",
    "wget_pipe_shell": "wget canalizado para shell",
    "schemeless_to_sink": "URL sem esquema em contexto de execução",
    "plain_http_to_sink": "URL HTTP sem TLS em contexto de execução",
    "base64_decode_execute": "Decodificação Base64 com execução",
    "confusable_domain": "Domínio confusível detectado",
    "punycode_domain": "Domínio punycode detectado",
    "shortened_url": "URL encurtada detectada",
    "raw_ip_url": "URL usa endereço IP bruto",
}

_SCAN_PREFIX_EN = "Security scan"
_SCAN_PREFIX_PT = "Varredura de segurança"

# Severidades exibidas no prompt de aprovação (Tirith usa inglês no JSON).
_SEVERITY_PT: dict[str, str] = {
    "CRITICAL": "CRÍTICA",
    "HIGH": "ALTA",
    "MEDIUM": "MÉDIA",
    "MED": "MÉDIA",
    "LOW": "BAIXA",
    "WARN": "AVISO",
    "WARNING": "AVISO",
    "INFO": "INFO",
}

_SUMMARY_PT: dict[str, str] = {
    "security issue detected": "problema de segurança detectado",
    "security warning detected": "aviso de segurança detectado",
    "security issue detected (details unavailable)": "problema de segurança detectado (detalhes indisponíveis)",
    "security warning detected (details unavailable)": "aviso de segurança detectado (detalhes indisponíveis)",
}

# Substituições em descrições (ordem: frases longas primeiro)
_DESC_PHRASES: tuple[tuple[str, str], ...] = (
    (
        "URL without explicit scheme passed to a command that downloads/executes content",
        "URL sem esquema explícito passada a um comando que baixa ou executa conteúdo",
    ),
    (
        "Downloaded content will be executed without inspection.",
        "O conteúdo baixado será executado sem inspeção.",
    ),
    (
        "Consider downloading first and reviewing.",
        "Considere baixar primeiro e revisar o conteúdo.",
    ),
    (
        "to inspect before executing.",
        "para inspecionar antes de executar.",
    ),
    ("Safer: ", "Mais seguro: "),
    (" — or: ", " — ou: "),
    (" - or: ", " — ou: "),
)

_PIPE_TO_INTERP_RE = re.compile(
    r"Command pipes output from '([^']+)' directly to interpreter '([^']+)'\.?\s*"
    r"(?:Downloaded content will be executed without inspection\.?)?",
    re.IGNORECASE,
)

_PIPE_TO_INTERP_TITLE_RE = re.compile(r"^Pipe to interpreter:\s*", re.IGNORECASE)


def _translate_title(title: str, rule_id: str = "") -> str:
    raw = (title or "").strip()
    if not raw:
        rid = (rule_id or "").strip().lower()
        return _TIRITH_RULE_ID_TITLE_PT.get(rid, "")

    if raw in _TIRITH_TITLE_PT:
        return _TIRITH_TITLE_PT[raw]

    m = _PIPE_TO_INTERP_TITLE_RE.match(raw)
    if m:
        suffix = raw[m.end() :]
        base = _TIRITH_TITLE_PT["Pipe to interpreter"]
        return f"{base}: {suffix}" if suffix else base

    # Título dinâmico "Pipe to interpreter: curl | bash"
    if raw.lower().startswith("pipe to interpreter:"):
        return _PIPE_TO_INTERP_TITLE_RE.sub(
            f"{_TIRITH_TITLE_PT['Pipe to interpreter']}: ", raw, count=1
        )

    return raw


def _translate_description(desc: str) -> str:
    text = (desc or "").strip()
    if not text:
        return ""

    m = _PIPE_TO_INTERP_RE.search(text)
    if m:
        repl = (
            f"O comando canaliza a saída de '{m.group(1)}' diretamente para o "
            f"interpretador '{m.group(2)}'. O conteúdo baixado será executado sem inspeção."
        )
        text = _PIPE_TO_INTERP_RE.sub(repl, text, count=1)

    for en, pt in _DESC_PHRASES:
        text = text.replace(en, pt)

    return text


def localize_tirith_severity(severity: str) -> str:
    """Traduz rótulos de severidade (HIGH → ALTA, MEDIUM → MÉDIA, …)."""
    key = (severity or "").strip().upper()
    if not key:
        return ""
    return _SEVERITY_PT.get(key, severity.strip())


def localize_tirith_finding(finding: dict) -> dict:
    """Retorna cópia do achado com title/description/severity em pt-BR."""
    rule_id = str(finding.get("rule_id") or finding.get("ruleId") or "")
    title = _translate_title(str(finding.get("title") or ""), rule_id)
    desc = _translate_description(str(finding.get("description") or ""))
    severity = localize_tirith_severity(str(finding.get("severity") or ""))
    out = dict(finding)
    if title:
        out["title"] = title
    if desc:
        out["description"] = desc
    if severity:
        out["severity"] = severity
    return out


def localize_tirith_scan_prefix(text: str) -> str:
    """Traduz o prefixo 'Security scan' em strings já formatadas."""
    if not text:
        return text
    if text.startswith(f"{_SCAN_PREFIX_EN} — "):
        return f"{_SCAN_PREFIX_PT} — {text[len(_SCAN_PREFIX_EN) + 3 :]}"
    if text.startswith(f"{_SCAN_PREFIX_EN}: "):
        return f"{_SCAN_PREFIX_PT}: {text[len(_SCAN_PREFIX_EN) + 2 :]}"
    return text


def localize_tirith_summary(summary: str) -> str:
    s = (summary or "").strip()
    return _SUMMARY_PT.get(s, s)
