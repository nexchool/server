"""Pure-Python tests for subject template models."""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from tests._model_loader import load_all_models  # noqa: E402

load_all_models()


def test_subject_template_group_to_dict():
    from modules.school_setup.template_models import SubjectTemplateGroup

    group = SubjectTemplateGroup(name="Test", board_code="custom", is_active=True)
    group.id = "g1"
    payload = group.to_dict()
    assert payload["board_code"] == "custom"
    assert payload["is_active"] is True
    assert payload["name"] == "Test"
    assert payload["id"] == "g1"


def test_subject_template_item_can_be_constructed():
    from modules.school_setup.template_models import SubjectTemplateItem

    item = SubjectTemplateItem(
        template_group_id="g1",
        grade_number=10,
        subject_name="Math",
        subject_code="MATH",
        periods_per_week=6,
        is_elective=False,
        sort_order=0,
    )
    assert item.subject_name == "Math"
    assert item.is_elective is False
    assert item.grade_number == 10
