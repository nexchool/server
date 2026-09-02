"""Nine modules recompute the setup flag, and all of them ignore failures.

Creating or deleting a class, grade, programme, school unit or subject context
can change whether a tenant's setup is still complete, so each of those
services calls `recompute_setup_complete` afterwards — every one of them
wrapped in

    try:
        recompute_setup_complete(tenant_id)
    except Exception:
        pass

Swallowing is the right call: the class was already created and committed, and
failing the request because a derived flag could not be refreshed would be
worse than the stale flag. What is not right is doing it silently. The function
exists to flip `is_setup_complete` back to false when setup drifts, so a failure
leaves a school marked complete when it is not — the onboarding wizard never
comes back and nobody is told the configuration is broken.

One helper, called from all nine, that degrades *and* says so.
"""

from __future__ import annotations

import logging

import pytest

from modules.school_setup.services import refresh_setup_status


def test_it_refreshes_the_flag(flask_app, tenant, db_session, monkeypatch):
    from modules.school_setup import services

    seen = []
    monkeypatch.setattr(services, "recompute_setup_complete",
                        lambda tid, **kw: seen.append(tid) or True)

    refresh_setup_status(tenant.id)

    assert seen == [tenant.id]


def test_a_failure_does_not_reach_the_caller(flask_app, tenant, db_session, monkeypatch):
    """The primary write already committed; this must not undo the response."""
    from modules.school_setup import services

    def _explode(tid, **kw):
        raise RuntimeError("status table is unhappy")

    monkeypatch.setattr(services, "recompute_setup_complete", _explode)

    refresh_setup_status(tenant.id)  # must not raise


def test_a_failure_is_logged_with_the_tenant(
    flask_app, tenant, db_session, monkeypatch, caplog
):
    """`except: pass` left a school silently marked complete when it was not."""
    from modules.school_setup import services

    def _explode(tid, **kw):
        raise RuntimeError("status table is unhappy")

    monkeypatch.setattr(services, "recompute_setup_complete", _explode)

    with caplog.at_level(logging.WARNING):
        refresh_setup_status(tenant.id)

    assert any(tenant.id in r.getMessage() for r in caplog.records), (
        "the failure was swallowed without naming the tenant"
    )


def test_a_missing_tenant_is_not_an_error(flask_app, db_session):
    """Callers pass whatever they have; some paths have no tenant in hand."""
    refresh_setup_status(None)  # must not raise


def test_no_module_swallows_the_recompute_silently():
    """The shape this replaces, pinned so it cannot be pasted back.

    Nine copies is how one of them ends up with a log and the rest do not.
    """
    import pathlib
    import re

    silent = re.compile(
        r"recompute_setup_complete\([^)]*\)\s*\n\s*except Exception:\s*\n\s*pass",
        re.M,
    )
    offenders = []
    for path in pathlib.Path("modules").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        if silent.search(path.read_text(errors="ignore")):
            offenders.append(str(path))

    assert offenders == [], (
        "these refresh the setup flag and discard any failure:\n  "
        + "\n  ".join(offenders)
    )
