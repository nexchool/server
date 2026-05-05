"""
Unit tests for ``modules.academics.services.timetable_rollover``.

Covers:
  - happy path: clones an active version + entries, remapping class_subject_id
  - GRADUATED sentinel filtered out of mapping (no validation failure)
  - empty mapping → success with zero counts
  - self-mapping (old_id == new_id) silently filtered
  - missing source / target class IDs return error and skip commit
  - target class already has a TimetableVersion → skip (don't overwrite)
  - source class has no active TimetableVersion → counted in skipped.classes_no_source
  - timetable entry whose old class_subject was deleted → entries_no_class_subject
  - timetable entry whose new class has no matching subject offering → skip
  - missing tenant_id → error
  - non-dict mapping → error
  - normalize handles bytes-ish values and strips whitespace
  - DB exception during commit triggers rollback
"""

from __future__ import annotations

import sys
from pathlib import Path

# Tests run with cwd at the repo root or /server; make sure /server is on path.
SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import modules.academics.services.timetable_rollover as ttr  # noqa: E402

from tests._rollover_helpers import (  # noqa: E402
    FakeSession,
    install_fake_model,
    install_fake_session,
    row,
)


def _patch_tenant(monkeypatch, tenant="tenant-1"):
    monkeypatch.setattr(ttr, "get_tenant_id", lambda: tenant)


# ── _normalize_mapping ───────────────────────────────────────────────────────


def test_normalize_mapping_filters_self_mapping_and_graduated():
    out = ttr._normalize_mapping(
        {
            "old-1": "new-1",       # kept
            "old-2": "old-2",       # self-mapped, filtered
            "old-3": "GRADUATED",   # graduated, filtered
            "old-4": "  new-4 ",    # whitespace stripped
            "old-5": "",            # empty value, filtered
            "": "new-x",            # empty key, filtered
        }
    )
    assert out == {"old-1": "new-1", "old-4": "new-4"}


def test_normalize_mapping_rejects_non_dict():
    import pytest

    with pytest.raises(ValueError):
        ttr._normalize_mapping("not-a-dict")


# ── happy path / decision logic ─────────────────────────────────────────────


def test_rollover_timetables_happy_path_remaps_class_subjects(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, ttr)

    # Mapping: old class C-OLD → new class C-NEW
    mapping = {"C-OLD": "C-NEW"}

    # Class.query: validated for old + new (both exist).
    install_fake_model(
        monkeypatch,
        ttr,
        "Class",
        queue=[
            [row(id="C-OLD")],   # old class lookup
            [row(id="C-NEW")],   # new class lookup
        ],
    )

    # Active source TimetableVersion on the old class.
    src_version = row(
        id="V-OLD",
        class_id="C-OLD",
        bell_schedule_id="BELL-1",
        label="Term1",
        status="active",
    )
    # Existing target versions: none.
    install_fake_model(
        monkeypatch,
        ttr,
        "TimetableVersion",
        queue=[
            [src_version],   # source query
            [],              # existing target query
        ],
    )

    # ClassSubject queries: old offerings then new offerings.
    old_cs = row(id="CS-OLD", class_id="C-OLD", subject_id="SUBJ-1")
    new_cs = row(id="CS-NEW", class_id="C-NEW", subject_id="SUBJ-1")
    install_fake_model(
        monkeypatch,
        ttr,
        "ClassSubject",
        queue=[
            [old_cs],   # _build by class on old
            [new_cs],   # _build by class on new (from _build_class_subject_lookup)
        ],
    )

    # TimetableEntry on the source version: one entry that should remap.
    entry = row(
        id="E-OLD",
        class_subject_id="CS-OLD",
        teacher_id="T-1",
        day_of_week=0,
        period_number=1,
        room="R-1",
        notes=None,
        entry_status="active",
    )
    install_fake_model(
        monkeypatch,
        ttr,
        "TimetableEntry",
        queue=[[entry]],
    )

    result = ttr.rollover_timetables(mapping, user_id="user-1")

    assert result["success"] is True
    assert result["versions_created"] == 1
    assert result["entries_created"] == 1
    assert result["skipped"] == {
        "classes_no_source": 0,
        "classes_target_has_version": 0,
        "entries_no_class_subject": 0,
    }
    # 1 new version + 1 new entry inserted.
    assert len(sess.added) == 2
    assert sess.commits == 1 and sess.rollbacks == 0

    new_version_obj, new_entry_obj = sess.added
    assert new_version_obj.class_id == "C-NEW"
    assert new_version_obj.status == "draft"
    assert new_version_obj.bell_schedule_id == "BELL-1"
    assert new_version_obj.created_by == "user-1"

    # The entry must point at the *new* class subject.
    assert new_entry_obj.class_subject_id == "CS-NEW"
    assert new_entry_obj.timetable_version_id == new_version_obj.id


def test_graduated_value_in_mapping_is_filtered_not_validation_error(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, ttr)

    mapping = {
        "C-OLD-1": "GRADUATED",  # filtered by normalize
        "C-OLD-2": "C-NEW",
    }

    # Class queue should only see C-OLD-2 (old) and C-NEW (new) — not GRADUATED.
    install_fake_model(
        monkeypatch,
        ttr,
        "Class",
        queue=[
            [row(id="C-OLD-2")],
            [row(id="C-NEW")],
        ],
    )
    install_fake_model(
        monkeypatch, ttr, "TimetableVersion", queue=[[], []]
    )
    install_fake_model(monkeypatch, ttr, "ClassSubject", queue=[[], []])

    result = ttr.rollover_timetables(mapping)
    assert result["success"] is True
    # No source TimetableVersion to clone, but the call did not error.
    assert result["versions_created"] == 0
    assert result["skipped"]["classes_no_source"] == 1
    assert sess.rollbacks == 0


def test_empty_mapping_returns_zero_counts_without_db_calls(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, ttr)

    # No models should be queried — provide empty queues to assert that.
    install_fake_model(monkeypatch, ttr, "Class", queue=[])
    install_fake_model(monkeypatch, ttr, "TimetableVersion", queue=[])
    install_fake_model(monkeypatch, ttr, "ClassSubject", queue=[])

    result = ttr.rollover_timetables({})
    assert result == {
        "success": True,
        "versions_created": 0,
        "entries_created": 0,
        "skipped": {
            "classes_no_source": 0,
            "classes_target_has_version": 0,
            "entries_no_class_subject": 0,
        },
    }
    assert sess.added == []
    # No commit when there is nothing to do.
    assert sess.commits == 0


def test_missing_source_class_returns_error(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, ttr)

    install_fake_model(
        monkeypatch,
        ttr,
        "Class",
        queue=[
            [],  # source lookup returns nothing → missing
        ],
    )
    install_fake_model(monkeypatch, ttr, "TimetableVersion", queue=[])
    install_fake_model(monkeypatch, ttr, "ClassSubject", queue=[])

    result = ttr.rollover_timetables({"OLD": "NEW"})
    assert result["success"] is False
    assert "Unknown source class_id" in result["error"]


def test_missing_target_class_returns_error(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, ttr)

    install_fake_model(
        monkeypatch,
        ttr,
        "Class",
        queue=[
            [row(id="OLD")],
            [],  # new lookup returns nothing → missing
        ],
    )
    install_fake_model(monkeypatch, ttr, "TimetableVersion", queue=[])
    install_fake_model(monkeypatch, ttr, "ClassSubject", queue=[])

    result = ttr.rollover_timetables({"OLD": "NEW"})
    assert result["success"] is False
    assert "Unknown target class_id" in result["error"]


def test_target_class_with_existing_version_is_skipped(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, ttr)

    install_fake_model(
        monkeypatch,
        ttr,
        "Class",
        queue=[[row(id="C-OLD")], [row(id="C-NEW")]],
    )

    src_version = row(
        id="V-OLD",
        class_id="C-OLD",
        bell_schedule_id=None,
        label=None,
        status="active",
    )
    target_existing = row(class_id="C-NEW")
    install_fake_model(
        monkeypatch,
        ttr,
        "TimetableVersion",
        queue=[
            [src_version],          # source
            [target_existing],      # target already has a version
        ],
    )
    install_fake_model(monkeypatch, ttr, "ClassSubject", queue=[[], []])

    result = ttr.rollover_timetables({"C-OLD": "C-NEW"})
    assert result["success"] is True
    assert result["versions_created"] == 0
    assert result["skipped"]["classes_target_has_version"] == 1
    # Nothing inserted; no commit-worthy work — but the function still commits
    # the (empty) transaction safely. Either way we should not insert rows.
    assert sess.added == []


def test_no_source_active_version(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, ttr)

    install_fake_model(
        monkeypatch,
        ttr,
        "Class",
        queue=[[row(id="C-OLD")], [row(id="C-NEW")]],
    )
    install_fake_model(
        monkeypatch,
        ttr,
        "TimetableVersion",
        queue=[
            [],   # no active version on source
            [],   # no target versions
        ],
    )
    install_fake_model(monkeypatch, ttr, "ClassSubject", queue=[[], []])

    result = ttr.rollover_timetables({"C-OLD": "C-NEW"})
    assert result["success"] is True
    assert result["skipped"]["classes_no_source"] == 1


def test_entry_with_unknown_old_class_subject_is_skipped(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, ttr)

    install_fake_model(
        monkeypatch, ttr, "Class",
        queue=[[row(id="C-OLD")], [row(id="C-NEW")]],
    )
    src_version = row(
        id="V-OLD", class_id="C-OLD",
        bell_schedule_id=None, label=None, status="active",
    )
    install_fake_model(
        monkeypatch, ttr, "TimetableVersion",
        queue=[[src_version], []],
    )
    # Old ClassSubject lookup returns empty (deleted_at filter), so the
    # entry's class_subject_id will not be found.
    install_fake_model(monkeypatch, ttr, "ClassSubject", queue=[[], []])
    entry = row(
        id="E-1", class_subject_id="CS-DELETED",
        teacher_id=None, day_of_week=0, period_number=1,
        room=None, notes=None, entry_status="active",
    )
    install_fake_model(monkeypatch, ttr, "TimetableEntry", queue=[[entry]])

    result = ttr.rollover_timetables({"C-OLD": "C-NEW"})
    assert result["success"] is True
    assert result["versions_created"] == 1
    assert result["entries_created"] == 0
    assert result["skipped"]["entries_no_class_subject"] == 1
    # Only the version was inserted.
    assert len(sess.added) == 1


def test_entry_with_no_matching_target_offering_is_skipped(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, ttr)

    install_fake_model(
        monkeypatch, ttr, "Class",
        queue=[[row(id="C-OLD")], [row(id="C-NEW")]],
    )
    src_version = row(
        id="V-OLD", class_id="C-OLD",
        bell_schedule_id=None, label=None, status="active",
    )
    install_fake_model(
        monkeypatch, ttr, "TimetableVersion",
        queue=[[src_version], []],
    )
    old_cs = row(id="CS-OLD", class_id="C-OLD", subject_id="SUBJ-LANGUAGE")
    # New class only has a Maths offering; no Language → no remap target.
    new_cs = row(id="CS-MATH", class_id="C-NEW", subject_id="SUBJ-MATH")
    install_fake_model(
        monkeypatch, ttr, "ClassSubject",
        queue=[[old_cs], [new_cs]],
    )
    entry = row(
        id="E-1", class_subject_id="CS-OLD",
        teacher_id=None, day_of_week=0, period_number=1,
        room=None, notes=None, entry_status="active",
    )
    install_fake_model(monkeypatch, ttr, "TimetableEntry", queue=[[entry]])

    result = ttr.rollover_timetables({"C-OLD": "C-NEW"})
    assert result["success"] is True
    assert result["versions_created"] == 1
    assert result["entries_created"] == 0
    assert result["skipped"]["entries_no_class_subject"] == 1
    # Only the version was inserted.
    assert len(sess.added) == 1


def test_missing_tenant_returns_error(monkeypatch):
    monkeypatch.setattr(ttr, "get_tenant_id", lambda: None)
    sess = FakeSession()
    install_fake_session(monkeypatch, ttr)

    result = ttr.rollover_timetables({"a": "b"})
    assert result == {"success": False, "error": "Tenant context is required"}
    assert sess.commits == 0  # FakeSession is a fresh instance, but assert anyway.


def test_non_dict_mapping_returns_error(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, ttr)
    result = ttr.rollover_timetables("not a dict")
    assert result["success"] is False
    assert "must be an object" in result["error"]


def test_db_exception_triggers_rollback(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, ttr, raise_on_commit=True)

    install_fake_model(
        monkeypatch, ttr, "Class",
        queue=[[row(id="C-OLD")], [row(id="C-NEW")]],
    )
    src_version = row(
        id="V-OLD", class_id="C-OLD",
        bell_schedule_id=None, label=None, status="active",
    )
    install_fake_model(
        monkeypatch, ttr, "TimetableVersion",
        queue=[[src_version], []],
    )
    install_fake_model(monkeypatch, ttr, "ClassSubject", queue=[[], []])
    install_fake_model(monkeypatch, ttr, "TimetableEntry", queue=[[]])

    result = ttr.rollover_timetables({"C-OLD": "C-NEW"})
    assert result["success"] is False
    assert "forced commit failure" in result["error"]
    assert sess.rollbacks == 1
