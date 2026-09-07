"""Shared builders for the Phase −1 characterization suite.

Plain functions rather than fixtures, deliberately: `tests/auth/` has no
conftest of its own today, and adding one risks shadowing a fixture that an
existing test in this directory already depends on. The project already uses
this shape — `tests/conftest.py` exposes `employ_for` / `grant_profile_to` as
importable helpers rather than fixtures.

Nothing here asserts anything. These builders only construct the *minimum*
account that today's login pipeline will actually let through, which is worth
stating because it is itself characterization:

    a login succeeds only if the account is email-verified, not suspended,
    not soft-deleted, and resolves to a NON-EMPTY permission set

— the last of which comes from an Authority Profile held by an employment
(ADR-013), never from the account. An account with no permissions gets 403
`NoPermissions` from `_finalize_login`, so a "happy path" test that forgets
the employment does not test the happy path.
"""

from __future__ import annotations

import uuid
from typing import Iterable, Optional

DEFAULT_PERMISSION = "student.read.all"


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def make_tenant(db_session, *, subdomain_prefix: str = "chz", **overrides):
    """An active tenant. Full uuid in the subdomain — committed tenants
    accumulate in the developer's database and short names collide."""
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    fields = dict(
        id=new_id("t-"),
        name="Characterization School",
        subdomain=f"{subdomain_prefix}-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    fields.update(overrides)
    t = Tenant(**fields)
    db_session.add(t)
    db_session.flush()
    return t


def make_user(
    db_session,
    tenant,
    *,
    password: str,
    email: Optional[str] = None,
    email_verified: bool = True,
    **overrides,
):
    """An account with a real password hash. No authority yet."""
    from modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    fields = dict(
        id=new_id("u-"),
        tenant_id=tenant.id,
        email=email or f"chz-{suffix}@test.school",
        name="Characterization User",
        email_verified=email_verified,
    )
    fields.update(overrides)
    user = User(**fields)
    user.set_password(password)
    db_session.add(user)
    db_session.flush()
    return user


def grant_permissions(db_session, tenant, user, permissions: Iterable[str] = ()):
    """Give this account's person an employment holding a profile with these keys.

    Authority is held by the employment, not the account (ADR-013), so the
    person is employed first — which is also the order a school does it in.
    """
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    role = Role(id=new_id("r-"), tenant_id=tenant.id, name=f"Chz-{suffix}")
    db_session.add(role)
    db_session.flush()

    for name in permissions or (DEFAULT_PERMISSION,):
        permission = Permission.query.filter_by(name=name).first()
        if permission is None:
            permission = Permission(id=new_id("perm-"), name=name)
            db_session.add(permission)
            db_session.flush()
        db_session.add(
            RolePermission(
                tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
            )
        )
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")
    return role


def make_account(
    db_session,
    tenant,
    *,
    password: str,
    permissions: Iterable[str] = (),
    **user_overrides,
):
    """The minimum account today's login pipeline lets through."""
    user = make_user(db_session, tenant, password=password, **user_overrides)
    grant_permissions(db_session, tenant, user, permissions)
    return user


def make_platform_admin(db_session, home_tenant, *, password: str):
    """A super-admin whose home tenant is not the one they will enter."""
    return make_user(
        db_session,
        home_tenant,
        password=password,
        email=f"chz-super-{uuid.uuid4().hex[:6]}@platform.test",
        name="Characterization Super Admin",
        is_platform_admin=True,
    )


def login(client, *, email, password, **body):
    """POST /api/auth/login. Extra kwargs go straight into the body."""
    payload = {"email": email, "password": password}
    payload.update(body)
    return client.post("/api/auth/login", json=payload)


def sessions_for(user_id):
    from modules.auth.models import Session

    return Session.query.filter_by(user_id=user_id).all()


def live_sessions_for(user_id):
    from modules.auth.models import Session

    return Session.query.filter_by(user_id=user_id, revoked=False).all()


def decode_access_token(token: str) -> dict:
    """Decode without going through validate_jwt_token, so the raw claim set
    is visible — including claims a future refactor might quietly drop."""
    import jwt

    from modules.auth.services import JWT_ALGORITHM, JWT_SECRET

    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def set_cookie_headers(response) -> list:
    return response.headers.getlist("Set-Cookie")


def auth_cookie(response) -> Optional[str]:
    for header in set_cookie_headers(response):
        if header.startswith("auth-token="):
            return header
    return None
