"""A key that has ever been stored cannot be trusted to default.

Migration 043 seeded every tenant's `feature_flags` from the feature list of
the day. `update_tenant_feature_flags` merges rather than prunes — deliberately,
because that column doubles as a per-tenant settings bag and pruning would
delete a school's `login_variant` — so those keys are still stored on live
tenants years later.

That is harmless until a key's stored value starts to matter. It did once: the
`examinations` module shipped in DEFAULT_OFF_FEATURES, where a *missing* key
means off, and a stored value beats a default — so every tenant that went
through 043 switched the module on the moment it deployed, which is exactly
what defaulting it off was meant to prevent. Migration 120 deleted that one key.

The trap itself is still there for the next module. These tests name the
poisoned keys so that reusing one fails here rather than in production.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from core.feature_flags import (
    DEFAULT_OFF_FEATURES,
    OPTIONAL_FEATURES,
    RETIRED_FEATURE_KEYS,
)


def test_a_retired_key_is_never_reused_as_a_default_off_feature():
    """The exact shape that bit in production.

    A module defaulting to off, under a key some tenants already have stored as
    true, is on for those tenants the day it deploys.
    """
    collisions = RETIRED_FEATURE_KEYS & DEFAULT_OFF_FEATURES

    assert collisions == set(), (
        f"{sorted(collisions)} default to off, but live tenants have a stored "
        "value for them from migration 043 — and a stored value beats a "
        "default. Pick a new key, or write a migration that deletes the stale "
        "one first (see 120_a_retired_feature_key_is_not_an_answer)."
    )


def test_a_retired_key_is_not_quietly_brought_back():
    """Reusing one as an ordinary optional feature is survivable but wrong.

    Those tenants would start with it on and no one would have chosen that;
    tenants created since would default to on too, so it *looks* consistent
    while resting on a value from a list nobody remembers.
    """
    revived = RETIRED_FEATURE_KEYS & set(OPTIONAL_FEATURES)

    assert revived == set(), (
        f"{sorted(revived)} were seeded by migration 043 and retired since. "
        "Their stored values are still on live tenants, so this key cannot "
        "mean what a fresh key would."
    )


def test_the_retired_list_matches_what_the_migration_documented():
    """The list is only useful if it stays true to the schema's history.

    Migration 120's docstring is where these were enumerated; keeping the two
    in step means the next person can trust either one.
    """
    migration = pathlib.Path(
        "migrations/versions/120_a_retired_feature_key_is_not_an_answer.py"
    ).read_text()

    for key in ("library", "inventory", "reports", "finance",
                "holiday_management", "schedule_management"):
        assert key in migration, (
            f"{key!r} is listed as retired but migration 120 does not mention "
            "it — one of the two is wrong about what 043 seeded."
        )
        assert key in RETIRED_FEATURE_KEYS


def test_examinations_is_no_longer_retired():
    """It is a real, shipped module now — and 120 deleted its stale key.

    Kept as a test rather than a comment because it is the one key whose
    history is genuinely resolved, and listing it as retired would wrongly
    forbid the module that exists.
    """
    assert "examinations" not in RETIRED_FEATURE_KEYS
    assert "examinations" in OPTIONAL_FEATURES
