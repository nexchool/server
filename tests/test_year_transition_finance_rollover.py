"""
Unit tests for ``modules.finance.services.rollover``.

Covers:
  - happy path: clones FeeStructure + components + class links
  - GRADUATED sentinel filtered from class_mapping
  - empty/None mapping → still clones structures (no class links)
  - existing same-name structure in target year → reused, components NOT re-added
  - target class already linked to a *different* structure for that year →
    skipped (regression test for the unique-constraint conflict bug)
  - unmapped source class → counted in skipped_unmapped
  - target class belongs to wrong academic year → error
  - same from/to year rejected
  - missing tenant
  - DB exception rolls back
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import modules.finance.services.rollover as fr  # noqa: E402

from tests._rollover_helpers import (  # noqa: E402
    install_fake_model,
    install_fake_session,
    row,
)


def _patch_tenant(monkeypatch, tenant="tenant-1"):
    monkeypatch.setattr(fr, "get_tenant_id", lambda: tenant)


# ── _normalize_mapping ───────────────────────────────────────────────────────


def test_normalize_drops_graduated_self_and_empty():
    out = fr._normalize_mapping(
        {
            "old": "new",
            "g": "GRADUATED",
            "self": "self",
            " ": "x",
            "empty-val": "",
        }
    )
    assert out == {"old": "new"}


def test_normalize_none_is_empty_dict():
    assert fr._normalize_mapping(None) == {}


def test_normalize_rejects_non_dict():
    import pytest
    with pytest.raises(ValueError):
        fr._normalize_mapping(["not", "a", "dict"])


# ── rollover_fee_structures ─────────────────────────────────────────────────


def _structure(id_, name, *, is_transport_only=False, components=()):
    return row(
        id=id_,
        name=name,
        is_transport_only=is_transport_only,
        due_date=date(2025, 7, 1),
        components=list(components),
    )


def _component(name, amount):
    return row(name=name, amount=Decimal(str(amount)), is_optional=False, sort_order=0)


def test_finance_happy_path_clones_structures_components_and_class_links(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, fr)

    src = _structure(
        "FS-OLD",
        "Tuition",
        components=[_component("Tuition", "1000"), _component("Lab", "200")],
    )
    install_fake_model(
        monkeypatch,
        fr,
        "Class",
        queue=[
            [row(id="C-NEW", academic_year_id="Y-2026")],   # validate target classes
        ],
    )
    install_fake_model(
        monkeypatch,
        fr,
        "FeeStructure",
        queue=[
            [src],   # source list
            [],      # existing target list (none)
        ],
    )
    install_fake_model(
        monkeypatch,
        fr,
        "FeeStructureClass",
        queue=[
            [],   # initial classes_already_linked snapshot
            [row(class_id="C-OLD")],   # source links for src
        ],
    )

    result = fr.rollover_fee_structures(
        "Y-2025", "Y-2026", {"C-OLD": "C-NEW"}
    )

    assert result["success"] is True
    assert result["structures_created"] == 1
    assert result["structures_reused"] == 0
    assert result["components_created"] == 2
    assert result["class_links_created"] == 1
    assert result["class_links_skipped_unmapped"] == 0
    assert result["class_links_skipped_conflict"] == 0
    # 1 structure + 2 components + 1 class link.
    assert len(sess.added) == 4
    assert sess.commits == 1 and sess.rollbacks == 0


def test_finance_existing_structure_reused_components_not_recreated(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, fr)

    src = _structure("FS-OLD", "Tuition", components=[_component("Tuition", "1000")])
    target_existing = _structure("FS-NEW-EXISTING", "Tuition")
    install_fake_model(
        monkeypatch, fr, "Class",
        queue=[[row(id="C-NEW", academic_year_id="Y-2026")]],
    )
    install_fake_model(
        monkeypatch, fr, "FeeStructure",
        queue=[[src], [target_existing]],
    )
    install_fake_model(
        monkeypatch, fr, "FeeStructureClass",
        queue=[
            [],   # nothing already linked
            [row(class_id="C-OLD")],
        ],
    )

    result = fr.rollover_fee_structures(
        "Y-2025", "Y-2026", {"C-OLD": "C-NEW"}
    )

    assert result["structures_created"] == 0
    assert result["structures_reused"] == 1
    assert result["components_created"] == 0   # do not re-add to existing structure
    assert result["class_links_created"] == 1
    # Only the class link was inserted.
    assert len(sess.added) == 1


def test_finance_class_already_linked_to_other_structure_is_skipped(monkeypatch):
    """Regression test: target class is already linked to a different fee
    structure for the same academic year. Without the conflict guard, this
    would trip the (tenant_id, academic_year_id, class_id) unique constraint."""
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, fr)

    src = _structure("FS-OLD", "Tuition", components=[])
    install_fake_model(
        monkeypatch, fr, "Class",
        queue=[[row(id="C-NEW", academic_year_id="Y-2026")]],
    )
    install_fake_model(
        monkeypatch, fr, "FeeStructure",
        queue=[[src], []],
    )
    install_fake_model(
        monkeypatch, fr, "FeeStructureClass",
        queue=[
            # C-NEW is already linked to OTHER-FS in the new year.
            [row(class_id="C-NEW", fee_structure_id="OTHER-FS")],
            # Source link for src.
            [row(class_id="C-OLD")],
        ],
    )

    result = fr.rollover_fee_structures(
        "Y-2025", "Y-2026", {"C-OLD": "C-NEW"}
    )

    assert result["success"] is True
    assert result["structures_created"] == 1
    assert result["class_links_created"] == 0
    assert result["class_links_skipped_conflict"] == 1
    # Only the structure was inserted (no class link).
    assert len(sess.added) == 1


def test_finance_unmapped_class_link_counted(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, fr)

    src = _structure("FS-OLD", "Tuition", components=[])
    install_fake_model(monkeypatch, fr, "Class", queue=[[]])
    install_fake_model(
        monkeypatch, fr, "FeeStructure",
        queue=[[src], []],
    )
    # Source link is for a class that isn't in the mapping.
    install_fake_model(
        monkeypatch, fr, "FeeStructureClass",
        queue=[[], [row(class_id="C-UNMAPPED")]],
    )

    result = fr.rollover_fee_structures("Y-2025", "Y-2026", {})
    assert result["class_links_skipped_unmapped"] == 1
    assert result["class_links_created"] == 0


def test_finance_target_class_wrong_year_returns_error(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, fr)

    install_fake_model(
        monkeypatch, fr, "Class",
        # The class exists but belongs to a DIFFERENT year.
        queue=[[row(id="C-NEW", academic_year_id="Y-2099")]],
    )
    install_fake_model(monkeypatch, fr, "FeeStructure", queue=[[], []])
    install_fake_model(monkeypatch, fr, "FeeStructureClass", queue=[[], []])

    result = fr.rollover_fee_structures(
        "Y-2025", "Y-2026", {"C-OLD": "C-NEW"}
    )
    assert result["success"] is False
    assert "do not belong" in result["error"]


def test_finance_unknown_target_class_returns_error(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, fr)

    install_fake_model(monkeypatch, fr, "Class", queue=[[]])

    result = fr.rollover_fee_structures(
        "Y-2025", "Y-2026", {"C-OLD": "C-MISSING"}
    )
    assert result["success"] is False
    assert "Unknown target class_id" in result["error"]


def test_finance_same_year_rejected(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, fr)
    result = fr.rollover_fee_structures("Y", "Y", {})
    assert result["success"] is False
    assert "must differ" in result["error"]


def test_finance_requires_tenant(monkeypatch):
    monkeypatch.setattr(fr, "get_tenant_id", lambda: None)
    install_fake_session(monkeypatch, fr)
    result = fr.rollover_fee_structures("Y-1", "Y-2", {})
    assert result == {"success": False, "error": "Tenant context is required"}


def test_finance_db_exception_rolls_back(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, fr, raise_on_commit=True)

    src = _structure("FS-OLD", "Tuition", components=[_component("Lab", "1")])
    install_fake_model(monkeypatch, fr, "Class", queue=[[]])
    install_fake_model(
        monkeypatch, fr, "FeeStructure",
        queue=[[src], []],
    )
    install_fake_model(monkeypatch, fr, "FeeStructureClass", queue=[[], []])

    result = fr.rollover_fee_structures("Y-2025", "Y-2026", {})
    assert result["success"] is False
    assert sess.rollbacks == 1


def test_finance_empty_mapping_still_clones_structures(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, fr)

    src = _structure("FS-OLD", "Tuition", components=[_component("X", "10")])
    install_fake_model(monkeypatch, fr, "Class", queue=[[]])
    install_fake_model(monkeypatch, fr, "FeeStructure", queue=[[src], []])
    install_fake_model(
        monkeypatch, fr, "FeeStructureClass",
        queue=[[], []],   # empty source links → no class link iteration
    )

    result = fr.rollover_fee_structures("Y-2025", "Y-2026", None)
    assert result["success"] is True
    assert result["structures_created"] == 1
    assert result["components_created"] == 1
    assert result["class_links_created"] == 0
    # Structure + component, no class link.
    assert len(sess.added) == 2
