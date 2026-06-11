"""Platform list_tenants search: case-insensitive contains-match on
name / subdomain / contact_email (the panel's jump-to-tenant box).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _make_tenant(db_session, name: str, subdomain: str, email: str | None = None):
    from core.models import Tenant

    t = Tenant(
        id=uuid.uuid4().hex,
        name=name,
        subdomain=subdomain,
        contact_email=email,
    )
    db_session.add(t)
    db_session.flush()
    return t


def _ids(result) -> set[str]:
    return {row["id"] for row in result["data"]}


def test_search_matches_name_subdomain_and_email_case_insensitively(
    flask_app, db_session
):
    from modules.platform import services

    uniq = uuid.uuid4().hex[:8]
    sunrise = _make_tenant(db_session, f"Sunrise School {uniq}", f"sunrise-{uniq}")
    moonlight = _make_tenant(
        db_session,
        f"Moonlight Academy {uniq}",
        f"moonlight-{uniq}",
        email=f"owner-{uniq}@moon.example",
    )

    with flask_app.test_request_context("/"):
        # Name fragment, wrong case -> only Sunrise.
        by_name = services.list_tenants(per_page=100, search=f"SUNRISE SCHOOL {uniq}")
        assert _ids(by_name) == {sunrise.id}

        # Subdomain fragment -> only Moonlight.
        by_sub = services.list_tenants(per_page=100, search=f"moonlight-{uniq}")
        assert _ids(by_sub) == {moonlight.id}

        # Email fragment -> only Moonlight.
        by_email = services.list_tenants(per_page=100, search=f"owner-{uniq}@")
        assert _ids(by_email) == {moonlight.id}

        # Shared fragment -> both, and the pagination total reflects the filter.
        both = services.list_tenants(per_page=100, search=uniq)
        assert _ids(both) == {sunrise.id, moonlight.id}
        assert both["pagination"]["total"] == 2

        # Non-match -> empty.
        none = services.list_tenants(per_page=100, search=f"zz-{uniq}-zz")
        assert none["data"] == []
        assert none["pagination"]["total"] == 0


def test_blank_search_is_ignored(flask_app, db_session):
    from modules.platform import services

    uniq = uuid.uuid4().hex[:8]
    t = _make_tenant(db_session, f"Blanks {uniq}", f"blanks-{uniq}")

    with flask_app.test_request_context("/"):
        result = services.list_tenants(per_page=100, search="   ")
        # Whitespace-only search behaves like no search: our tenant is in the
        # unfiltered set.
        assert t.id in _ids(result) or result["pagination"]["total"] > 1
