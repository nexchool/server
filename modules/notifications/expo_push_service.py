"""
Expo Push Notification API (HTTPS) for ExpoPushToken[...] tokens.

No extra Python deps — uses stdlib urllib.

Optional: EXPO_ACCESS_TOKEN for higher rate limits (Expo dashboard).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def send_expo_push(
    *,
    expo_push_token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
) -> Tuple[bool, bool]:
    """
    Send one Expo push notification.

    Returns:
        (delivered_ok, should_deactivate_token)
    """
    msg = {
        "to": expo_push_token,
        "title": title[:200],
        "body": (body or "")[:2000],
        "sound": "default",
        "priority": "high",
        "channelId": "default",
    }
    if data:
        msg["data"] = data

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }
    token = os.getenv("EXPO_ACCESS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body_bytes = json.dumps([msg]).encode("utf-8")
    req = urllib.request.Request(EXPO_PUSH_URL, data=body_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.exception("Expo push network error: %s", e)
        return False, False

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Expo push invalid JSON: %s", raw[:300])
        return False, False

    data_list = parsed.get("data") or []
    if not data_list:
        return False, False
    item = data_list[0]
    status = item.get("status")
    if status == "ok":
        return True, False
    err = (item.get("message") or "").lower()
    details = item.get("details") or {}
    derr = str(details.get("error") or "").lower()
    if "devicenotregistered" in derr or "invalidcredentials" in err:
        return False, True
    logger.warning("Expo push error: %s", item)
    return False, False


def send_expo_push_batch(
    messages: List[Dict],
) -> List[Tuple[str, bool, bool]]:
    """
    Batch send (Expo accepts multiple messages per request).

    Each message dict must include keys: to, title, body, optional data.

    Returns list of (token, ok, deactivate).
    """
    if not messages:
        return []
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }
    token = os.getenv("EXPO_ACCESS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body_bytes = json.dumps(messages).encode("utf-8")
    req = urllib.request.Request(EXPO_PUSH_URL, data=body_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.exception("Expo batch push error: %s", e)
        return [(m.get("to", ""), False, False) for m in messages]

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [(m.get("to", ""), False, False) for m in messages]

    out: List[Tuple[str, bool, bool]] = []
    data_list = parsed.get("data") or []
    for i, m in enumerate(messages):
        tok = m.get("to", "")
        item = data_list[i] if i < len(data_list) else {}
        status = item.get("status")
        if status == "ok":
            out.append((tok, True, False))
            continue
        details = item.get("details") or {}
        derr = str(details.get("error") or "").lower()
        err = (item.get("message") or "").lower()
        deactivate = "devicenotregistered" in derr or "invalidcredentials" in err
        out.append((tok, False, deactivate))
    return out
