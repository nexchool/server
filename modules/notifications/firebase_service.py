"""
Firebase Cloud Messaging HTTP v1 (service account OAuth2).

Env:
  FIREBASE_SERVICE_ACCOUNT_PATH — path to service account JSON file
  FIREBASE_SERVICE_ACCOUNT_JSON — inline JSON string (optional alternative)
  FCM_PROJECT_ID — optional override (else read from service account project_id)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_SCOPES = ("https://www.googleapis.com/auth/firebase.messaging",)

_lock = threading.Lock()
_credentials: Any = None
_project_id: Optional[str] = None
_token: str = ""
_token_expiry: float = 0.0


def _load_credentials():
    global _credentials, _project_id
    if _credentials is not None:
        return
    path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "").strip()
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not path and not raw:
        raise RuntimeError(
            "FCM not configured: set FIREBASE_SERVICE_ACCOUNT_PATH or FIREBASE_SERVICE_ACCOUNT_JSON"
        )
    if path:
        from google.oauth2 import service_account

        _credentials = service_account.Credentials.from_service_account_file(
            path, scopes=_SCOPES
        )
        with open(path, "r", encoding="utf-8") as f:
            info = json.load(f)
        _project_id = os.getenv("FCM_PROJECT_ID") or info.get("project_id")
    else:
        from google.oauth2 import service_account

        info = json.loads(raw)
        _credentials = service_account.Credentials.from_service_account_info(
            info, scopes=_SCOPES
        )
        _project_id = os.getenv("FCM_PROJECT_ID") or info.get("project_id")
    if not _project_id:
        raise RuntimeError("FCM project_id missing: set FCM_PROJECT_ID or use valid service account JSON")


def is_fcm_configured() -> bool:
    try:
        path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "").strip()
        raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        return bool(path or raw)
    except Exception:
        return False


def get_access_token() -> str:
    """Return a valid OAuth2 access token (cached until ~60s before expiry)."""
    global _token, _token_expiry
    with _lock:
        _load_credentials()
        now = time.time()
        if _token and _token_expiry > now + 60:
            return _token
        from google.auth.transport.requests import Request

        _credentials.refresh(Request())
        _token = _credentials.token or ""
        exp = getattr(_credentials, "expiry", None)
        if exp is not None:
            _token_expiry = exp.timestamp()
        else:
            _token_expiry = now + 3500
        return _token


def send_fcm_v1(
    *,
    device_token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
) -> Tuple[bool, bool]:
    """
    Send a single FCM v1 message.

    Returns:
        (delivered_ok, should_deactivate_token)
    """
    if not is_fcm_configured():
        logger.warning("FCM send skipped: not configured")
        return False, False

    try:
        access = get_access_token()
    except Exception as e:
        logger.exception("FCM OAuth failed: %s", e)
        return False, False

    _load_credentials()
    assert _project_id
    url = f"https://fcm.googleapis.com/v1/projects/{_project_id}/messages:send"
    payload: Dict[str, Any] = {
        "message": {
            "token": device_token,
            "notification": {"title": title[:200], "body": (body or "")[:2000]},
        }
    }
    if data:
        payload["message"]["data"] = data

    body_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body_bytes,
        headers={
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if 200 <= resp.status < 300:
                return True, False
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        logger.warning("FCM HTTP %s: %s", e.code, err_body[:500])
        lower = err_body.lower()
        if e.code == 404 or "unregistered" in lower or "not a valid fcm registration token" in lower:
            return False, True
        if e.code == 400 and ("invalid" in lower or "malformed" in lower):
            return False, True
        return False, False
    except Exception as e:
        logger.exception("FCM network error: %s", e)
        return False, False
    return True, False
