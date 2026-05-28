import pytest
from modules.search.services import global_search, _clamp_limit


def test_clamp_limit():
    assert _clamp_limit(5) == 5
    assert _clamp_limit(99) == 10
    assert _clamp_limit(0) == 1
    assert _clamp_limit(-3) == 1


def test_short_query_returns_empty_groups(tenant_ctx, admin_user):
    assert global_search(admin_user, "a", limit=5) == {"students": [], "teachers": [], "classes": [], "fees": []}


def test_empty_query_returns_empty_groups(tenant_ctx, admin_user):
    assert global_search(admin_user, "", limit=5)["students"] == []


def test_returns_all_group_keys(tenant_ctx, admin_user):
    result = global_search(admin_user, "zzz", limit=5)
    assert set(result.keys()) == {"students", "teachers", "classes", "fees"}
