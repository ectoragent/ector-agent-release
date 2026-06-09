from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class NginxSetupOptions:
    server_name: str = "_"
    listen_port: int = 9000
    upstream_host: str = "127.0.0.1"
    upstream_port: int = 9000
    email: Optional[str] = None
    enable_tls: bool = True
    enable_basic_auth: bool = False
    basic_user: str = "ector"
    basic_password: Optional[str] = None
    allow_ips: tuple[str, ...] = ()


def _run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _sudo_n(cmd: list[str]) -> subprocess.CompletedProcess:
    return _run(["sudo", "-n", *cmd])


def _is_ubuntu_like() -> bool:
    try:
        raw = Path("/etc/os-release").read_text()
        return "ID=ubuntu" in raw or "ID=debian" in raw or "ID_LIKE=debian" in raw
    except Exception:
        return False


def _nginx_server_block(opts: NginxSetupOptions) -> str:
    allow_lines = ""
    if opts.allow_ips:
        allow_lines = "\n".join([f"    allow {ip};" for ip in opts.allow_ips]) + "\n    deny all;\n"

    basic_auth = ""
    if opts.enable_basic_auth:
        basic_auth = (
            "    auth_basic \"Ector Dashboard\";\n"
            "    auth_basic_user_file /etc/nginx/.htpasswd-ector;\n"
        )

    make_default = (opts.server_name or "").strip() in {"_", "*"}
    listen_flags = " default_server" if make_default else ""

    return f"""server {{
  listen {int(opts.listen_port)}{listen_flags};
  server_name {opts.server_name};

  location / {{
    proxy_pass http://{opts.upstream_host}:{opts.upstream_port};
    proxy_http_version 1.1;

    # Upstream host_header guard expects loopback binds; keep Host as upstream.
    proxy_set_header Host {opts.upstream_host};
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket (PTY / chat)
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection \"upgrade\";

{basic_auth}{allow_lines}  }}
}}
"""


def _disable_default_site_if_present() -> None:
    """Disable Ubuntu's default site so our IP-based vhost becomes effective."""
    default_site = Path("/etc/nginx/sites-enabled/default")
    if default_site.exists():
        _sudo_n(["rm", "-f", str(default_site)])


def _write_nginx_site_conf(name: str, content: str) -> None:
    target = Path("/etc/nginx/sites-available") / name
    tmp = Path("/tmp") / f"{name}.tmp"
    tmp.write_text(content)
    res = _sudo_n(["install", "-m", "0644", str(tmp), str(target)])
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "Falha ao gravar config do Nginx (sudo?)")


def _enable_nginx_site(name: str) -> None:
    src = Path("/etc/nginx/sites-available") / name
    dst = Path("/etc/nginx/sites-enabled") / name
    _sudo_n(["ln", "-sf", str(src), str(dst)])


def _ensure_packages_installed() -> None:
    # Best-effort: only on Ubuntu/Debian-like hosts.
    if not _is_ubuntu_like():
        return
    need = ["nginx"]
    # certbot packages only when we enable TLS.
    # installed later by caller if requested.
    res = _sudo_n(["apt-get", "update", "-y"])
    if res.returncode != 0:
        return
    _sudo_n(["apt-get", "install", "-y", *need])


def _ensure_basic_auth_tool() -> None:
    if not _is_ubuntu_like():
        return
    # `htpasswd` is in apache2-utils.
    _sudo_n(["apt-get", "update", "-y"])
    _sudo_n(["apt-get", "install", "-y", "apache2-utils"])


def _write_htpasswd(user: str, password: str) -> None:
    # Use htpasswd if available, else fall back to openssl -apr1.
    htpasswd = _run(["bash", "-lc", "command -v htpasswd"]).stdout.strip()
    out_file = "/etc/nginx/.htpasswd-ector"
    if htpasswd:
        # -b: password on CLI (non-interactive). File permissions handled by nginx.
        res = _sudo_n(["htpasswd", "-bc", out_file, user, password])
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip() or "Falha ao gerar htpasswd")
        return

    # openssl fallback
    openssl = _run(["bash", "-lc", "command -v openssl"]).stdout.strip()
    if not openssl:
        raise RuntimeError("Nem `htpasswd` nem `openssl` estão disponíveis para Basic Auth.")
    pw_hash = _run(["bash", "-lc", f"openssl passwd -apr1 {subprocess.list2cmdline([password])}"]).stdout.strip()
    line = f"{user}:{pw_hash}\n"
    tmp = Path("/tmp/htpasswd-ector.tmp")
    tmp.write_text(line)
    res = _sudo_n(["install", "-m", "0640", str(tmp), out_file])
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "Falha ao gravar htpasswd")


def _nginx_test_and_reload() -> None:
    test = _sudo_n(["nginx", "-t"])
    if test.returncode != 0:
        raise RuntimeError(test.stderr.strip() or "nginx -t falhou")
    reload = _sudo_n(["systemctl", "reload", "nginx"])
    if reload.returncode != 0:
        # fallback to restart
        _sudo_n(["systemctl", "restart", "nginx"])


def disable_nginx_ector_dashboard_site() -> bool:
    """Disable the ector-dashboard nginx site and reload nginx.

    Returns True if the site link existed and was removed.
    """
    link = Path("/etc/nginx/sites-enabled/ector-dashboard")
    existed = link.exists()
    if existed:
        _sudo_n(["rm", "-f", str(link)])
        _nginx_test_and_reload()
    return existed


def _certbot_nginx(domain: str, email: str) -> None:
    if not _is_ubuntu_like():
        raise RuntimeError("TLS automático via Certbot só está automatizado para Ubuntu/Debian neste script.")
    _sudo_n(["apt-get", "update", "-y"])
    _sudo_n(["apt-get", "install", "-y", "certbot", "python3-certbot-nginx"])
    res = _sudo_n(
        [
            "certbot",
            "--nginx",
            "-d",
            domain,
            "--non-interactive",
            "--agree-tos",
            "-m",
            email,
            "--redirect",
        ]
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "Certbot falhou")


def setup_nginx_for_ector_dashboard(opts: NginxSetupOptions) -> None:
    server_name = (opts.server_name or "").strip()
    if not server_name or " " in server_name:
        raise ValueError("server_name inválido")
    if opts.enable_tls:
        # Certbot needs a real domain name that resolves to this host.
        if server_name in {"_", "*"}:
            raise ValueError("Para TLS automático, use um domínio real em --server-name.")
        if not (opts.email and "@" in opts.email):
            raise ValueError("Para TLS automático, passe --email válido.")
    if opts.enable_basic_auth and not opts.basic_password:
        raise ValueError("Basic Auth habilitado mas senha ausente.")

    _ensure_packages_installed()

    site_name = "ector-dashboard"
    conf = _nginx_server_block(opts)
    _write_nginx_site_conf(site_name, conf)
    _enable_nginx_site(site_name)

    # If we are using a catch-all server_name, ensure it takes precedence.
    if server_name in {"_", "*"}:
        _disable_default_site_if_present()

    if opts.enable_basic_auth:
        _ensure_basic_auth_tool()
        _write_htpasswd(opts.basic_user, opts.basic_password or "")

    _nginx_test_and_reload()

    if opts.enable_tls:
        _certbot_nginx(server_name, opts.email or "")

