"""Register / unregister device push tokens."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.database import db
from modules.auth.models import User
from modules.devices.models import DeviceToken

logger = logging.getLogger(__name__)

ALLOWED_PLATFORMS = frozenset({"android", "ios"})
ALLOWED_PROVIDERS = frozenset({"expo", "fcm"})
TOKEN_MAX_LEN = 512
# Alphanumeric + typical Expo/FCM punctuation
_TOKEN_SAFE = re.compile(r"^[\w\-\[\]:.@+/=]+$")


def _infer_provider(device_token: str, explicit: Optional[str]) -> str:
    if explicit and explicit.lower() in ALLOWED_PROVIDERS:
        return explicit.lower()
    t = device_token.strip()
    if t.startswith("ExponentPushToken[") or t.startswith("ExpoPushToken["):
        return "expo"
    return "fcm"


def register_device_token(
    *,
    tenant_id: str,
    user_id: str,
    device_token: str,
    platform: str,
    provider: Optional[str] = None,
    app_version: Optional[str] = None,
) -> Tuple[Optional[DeviceToken], Optional[str]]:
    """
    Upsert by device_token: reassign user/tenant if token already exists.

    Returns (DeviceToken, error_message).
    """
    raw = (device_token or "").strip()
    if not raw or len(raw) > TOKEN_MAX_LEN:
        return None, "device_token is required and must be under 512 characters"
    if not _TOKEN_SAFE.match(raw):
        return None, "device_token contains invalid characters"

    plat = (platform or "").strip().lower()
    if plat not in ALLOWED_PLATFORMS:
        return None, "platform must be android or ios"

    user = User.query.filter_by(id=user_id, tenant_id=tenant_id).first()
    if not user:
        return None, "User not found for tenant"

    if user.login_locked_until and user.login_locked_until > datetime.utcnow():
        return None, "Account temporarily locked"

    prov = _infer_provider(raw, provider)
    now = datetime.utcnow()
    app_ver = (app_version or "").strip()[:40] or None

    existing = DeviceToken.query.filter_by(device_token=raw).first()
    if existing:
        if existing.tenant_id != tenant_id:
            logger.warning(
                "device_token reassigned across tenants (token=%s...)", raw[:16]
            )
        existing.user_id = user_id
        existing.tenant_id = tenant_id
        existing.platform = plat
        existing.provider = prov
        existing.app_version = app_ver
        existing.is_active = True
        existing.last_used_at = now
        existing.updated_at = now
        db.session.add(existing)
        return existing, None

    row = DeviceToken(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        device_token=raw,
        platform=plat,
        provider=prov,
        app_version=app_ver,
        is_active=True,
        last_used_at=now,
    )
    db.session.add(row)
    return row, None


def unregister_device_token(
    *,
    tenant_id: str,
    user_id: str,
    device_token: str,
) -> Tuple[bool, Optional[str]]:
    raw = (device_token or "").strip()
    if not raw:
        return False, "device_token is required"

    row = DeviceToken.query.filter_by(device_token=raw).first()
    if not row:
        return True, None
    if row.tenant_id != tenant_id or row.user_id != user_id:
        return False, "Token not registered for this user"
    row.is_active = False
    row.updated_at = datetime.utcnow()
    db.session.add(row)
    return True, None


def list_active_tokens_for_user(tenant_id: str, user_id: str) -> List[DeviceToken]:
    """All active tokens for user within tenant (single query)."""
    return (
        DeviceToken.query.filter(
            DeviceToken.tenant_id == tenant_id,
            DeviceToken.user_id == user_id,
            DeviceToken.is_active.is_(True),
        )
        .order_by(DeviceToken.last_used_at.desc())
        .all()
    )


def deactivate_tokens_by_ids(token_row_ids: List[str]) -> int:
    if not token_row_ids:
        return 0
    return (
        DeviceToken.query.filter(DeviceToken.id.in_(token_row_ids))
        .update(
            {"is_active": False, "updated_at": datetime.utcnow()},
            synchronize_session=False,
        )
    )


def sanitize_push_data(data: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """FCM data payload: string values only, safe keys."""
    out: Dict[str, str] = {}
    if not data:
        return out
    for k, v in data.items():
        if v is None:
            continue
        ks = str(k)[:64]
        if not ks or ks.startswith("_"):
            continue
        out[ks] = str(v)[:1024]
    return out
