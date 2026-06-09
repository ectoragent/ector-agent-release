import base64
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from ector_constants import get_ector_home


_AUTH_DIR_NAME = "dashboard"
_AUTH_SECRET_FILE = "auth_secret.key"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * ((4 - (len(s) % 4)) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def _get_secret_path() -> Path:
    return get_ector_home() / _AUTH_DIR_NAME / _AUTH_SECRET_FILE


def _read_or_create_secret() -> bytes:
    path = _get_secret_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        data = path.read_bytes()
        if len(data) >= 32:
            return data
    data = os.urandom(32)
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except Exception:
        # Best-effort (Windows / restricted FS).
        pass
    return data


@dataclass(frozen=True)
class DashboardTokenPayload:
    exp: int
    nonce: str
    v: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {"v": self.v, "exp": self.exp, "nonce": self.nonce}


def create_dashboard_access_token(*, ttl_seconds: int) -> str:
    ttl = int(ttl_seconds)
    if ttl <= 0 or ttl > 60 * 60 * 24 * 30:
        raise ValueError("ttl_seconds must be within (0, 30 days]")

    secret = _read_or_create_secret()
    payload = DashboardTokenPayload(
        exp=int(time.time()) + ttl,
        nonce=str(uuid4()),
    )
    payload_bytes = json.dumps(payload.to_dict(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    sig = hmac.new(secret, payload_b64.encode("ascii"), digestmod="sha256").digest()
    sig_b64 = _b64url_encode(sig)
    return f"{payload_b64}.{sig_b64}"


def verify_dashboard_access_token(token: str) -> Tuple[bool, Optional[DashboardTokenPayload]]:
    t = (token or "").strip()
    if not t or "." not in t:
        return False, None
    try:
        payload_b64, sig_b64 = t.split(".", 1)
        secret = _read_or_create_secret()
        expected_sig = hmac.new(secret, payload_b64.encode("ascii"), digestmod="sha256").digest()
        if not hmac.compare_digest(_b64url_encode(expected_sig), sig_b64):
            return False, None
        payload_raw = _b64url_decode(payload_b64)
        parsed: Any = json.loads(payload_raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            return False, None
        v = int(parsed.get("v", 0))
        exp = int(parsed.get("exp", 0))
        nonce = str(parsed.get("nonce", "")).strip()
        if v != 1 or not nonce:
            return False, None
        if exp <= int(time.time()):
            return False, None
        return True, DashboardTokenPayload(v=v, exp=exp, nonce=nonce)
    except Exception:
        return False, None

