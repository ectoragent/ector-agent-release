"""Stable CLI installation identity (per ECTOR_HOME).

Persists ``device.json`` with ``install_id`` (UUID) and API-signed ``device_token``.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import stat
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from ector_constants import get_ector_home

logger = logging.getLogger(__name__)

DEVICE_STORE_VERSION = 1


def _device_file_path() -> Path:
    return get_ector_home() / "device.json"


def _default_label() -> str:
    try:
        return socket.gethostname().strip() or "CLI"
    except OSError:
        return "CLI"


def load_device_store() -> Dict[str, Any]:
    path = _device_file_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("device_identity: failed to read %s (%s)", path, exc)
        return {}


def _write_device_store(data: Dict[str, Any]) -> None:
    path = _device_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": DEVICE_STORE_VERSION,
        "install_id": str(data.get("install_id") or ""),
        "device_token": str(data.get("device_token") or ""),
        "label": str(data.get("label") or _default_label()),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def get_or_create_install_id() -> str:
    store = load_device_store()
    install_id = str(store.get("install_id") or "").strip()
    if install_id:
        return install_id
    install_id = str(uuid.uuid4())
    store["install_id"] = install_id
    if not store.get("label"):
        store["label"] = _default_label()
    _write_device_store(store)
    return install_id


def get_device_label() -> str:
    store = load_device_store()
    label = str(store.get("label") or "").strip()
    return label or _default_label()


def get_device_token() -> Optional[str]:
    token = str(load_device_store().get("device_token") or "").strip()
    return token or None


def device_auth_headers() -> Dict[str, str]:
    install_id = str(load_device_store().get("install_id") or "").strip()
    token = get_device_token()
    headers: Dict[str, str] = {}
    if install_id:
        headers["x-ector-install-id"] = install_id
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def register_device_with_api(
    *,
    base_url: str,
    access_token: str,
    timeout: float = 20.0,
) -> Optional[str]:
    """Register install with API; persist device_token. Returns token or None."""
    install_id = get_or_create_install_id()
    label = get_device_label()
    url = f"{base_url.rstrip('/')}/agent/devices/register"
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            response = client.post(
                url,
                json={"installId": install_id, "label": label},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("device_identity: register failed (network): %s", exc)
        return None

    if response.status_code not in (200, 201):
        logger.warning(
            "device_identity: register failed HTTP %s: %s",
            response.status_code,
            response.text[:200],
        )
        return None

    try:
        body = response.json()
    except json.JSONDecodeError:
        return None

    device_token = str(body.get("deviceToken") or "").strip()
    if not device_token:
        return None

    store = load_device_store()
    store["install_id"] = install_id
    store["device_token"] = device_token
    store["label"] = label
    _write_device_store(store)
    return device_token


def cli_oauth_query_params() -> Dict[str, str]:
    """Query params for GET /agent/auth (loopback login)."""
    params: Dict[str, str] = {"install_id": get_or_create_install_id()}
    token = get_device_token()
    if token:
        params["device_token"] = token
    label = get_device_label()
    if label:
        params["device_label"] = label
    return params
