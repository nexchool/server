"""
Deliver push notifications to stored device tokens (FCM and Expo).
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Tuple

from modules.devices.device_service import deactivate_tokens_by_ids
from modules.devices.models import DeviceToken
from modules.notifications.expo_push_service import send_expo_push
from modules.notifications.firebase_service import is_fcm_configured, send_fcm_v1

logger = logging.getLogger(__name__)

_HTML_TAG = re.compile(r"<[^>]+>")


def strip_html_for_push(text: str, max_len: int = 1800) -> str:
    if not text:
        return ""
    plain = _HTML_TAG.sub(" ", text)
    plain = " ".join(plain.split())
    return plain[:max_len]


def _send_one(row: DeviceToken, title: str, body: str, data: Dict[str, str]) -> Tuple[bool, bool]:
    if row.provider == "expo":
        return send_expo_push(
            expo_push_token=row.device_token,
            title=title,
            body=body,
            data=data or None,
        )
    if not is_fcm_configured():
        logger.warning("FCM token skipped (not configured): user device id=%s", row.id)
        return False, False
    return send_fcm_v1(
        device_token=row.device_token,
        title=title,
        body=body,
        data=data or None,
    )


def deliver_to_tokens(
    tokens: List[DeviceToken],
    *,
    title: str,
    body: str,
    data: Dict[str, str],
) -> Dict[str, int]:
    """
    Send to each token; retry once on transient failure; deactivate invalid tokens.

    Returns counts: ok, failed, deactivated.
    """
    ok = failed = deactivated = 0
    if not tokens:
        return {"ok": 0, "failed": 0, "deactivated": 0}

    for row in tokens:
        success, deact = _send_one(row, title, body, data)
        if success:
            ok += 1
            continue
        if deact:
            deactivate_tokens_by_ids([row.id])
            deactivated += 1
            continue
        success2, deact2 = _send_one(row, title, body, data)
        if success2:
            ok += 1
        elif deact2:
            deactivate_tokens_by_ids([row.id])
            deactivated += 1
        else:
            failed += 1

    return {"ok": ok, "failed": failed, "deactivated": deactivated}
