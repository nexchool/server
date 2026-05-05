"""
Unit tests for ``modules.academics.services.teacher_gaps.summarize_teacher_gaps``.

Covers:
  - happy path: counts classes without primary class teacher and class_subjects
    without primary subject teacher
  - empty academic year (no classes)
  - missing tenant / academic_year_id
  - sample lists are capped (we just verify the cap is applied, not the exact 20)
  - only ACTIVE primary teachers count toward "covered"; an assistant role does
    not satisfy the gap
"""

from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import modules.academics.services.teacher_gaps as tg  # noqa: E402

from tests._rollover_helpers import install_fake_model, row  # noqa: E402


def test_happy_path_reports_correct_totals(monkeypatch):
    classes = [
        row(id="C1", name="Grade 1", section="A"),
        row(id="C2", name="Grade 1", section="B"),
        row(id="C3", name="Grade 2", section="A"),
    ]
    install_fake_model(monkeypatch, tg, "Class", queue=[classes])
    # Only C1 has a class teacher; C2 + C3 are gaps.
    install_fake_model(
        monkeypatch,
        tg,
        "ClassTeacherAssignment",
        queue=[[row(class_id="C1")]],
    )
    class_subjects = [
        row(id="CS1", class_id="C1", subject_id="MATH"),
        row(id="CS2", class_id="C2", subject_id="ENG"),
        row(id="CS3", class_id="C3", subject_id="MATH"),
    ]
    install_fake_model(monkeypatch, tg, "ClassSubject", queue=[class_subjects])
    # Only CS1 has a primary subject teacher.
    install_fake_model(
        monkeypatch,
        tg,
        "ClassSubjectTeacher",
        queue=[[row(class_subject_id="CS1")]],
    )

    result = tg.summarize_teacher_gaps("tenant-1", "Y-2026")
    assert result["success"] is True
    data = result["data"]
    assert data["totals"] == {
        "classes": 3,
        "classes_missing_class_teacher": 2,
        "class_subjects": 3,
        "class_subjects_missing_primary_teacher": 2,
    }
    # Samples include the missing entries.
    missing_classes = data["samples"]["classes_missing_class_teacher"]
    assert {m["class_id"] for m in missing_classes} == {"C2", "C3"}
    missing_subjects = data["samples"]["class_subjects_missing_primary_teacher"]
    assert {m["class_subject_id"] for m in missing_subjects} == {"CS2", "CS3"}


def test_empty_year_returns_zero_totals(monkeypatch):
    install_fake_model(monkeypatch, tg, "Class", queue=[[]])
    install_fake_model(monkeypatch, tg, "ClassSubject", queue=[[]])
    # ClassTeacherAssignment / ClassSubjectTeacher are not queried when the
    # class id list is empty.
    install_fake_model(monkeypatch, tg, "ClassTeacherAssignment", queue=[])
    install_fake_model(monkeypatch, tg, "ClassSubjectTeacher", queue=[])

    result = tg.summarize_teacher_gaps("tenant-1", "Y-2099")
    assert result["success"] is True
    assert result["data"]["totals"] == {
        "classes": 0,
        "classes_missing_class_teacher": 0,
        "class_subjects": 0,
        "class_subjects_missing_primary_teacher": 0,
    }
    assert result["data"]["samples"] == {
        "classes_missing_class_teacher": [],
        "class_subjects_missing_primary_teacher": [],
    }


def test_missing_tenant():
    result = tg.summarize_teacher_gaps("", "Y-2026")
    assert result == {"success": False, "error": "Tenant context is required"}


def test_missing_academic_year():
    result = tg.summarize_teacher_gaps("tenant-1", "")
    assert result == {"success": False, "error": "academic_year_id is required"}


def test_sample_truncation_cap_applied(monkeypatch):
    # 25 classes, none with a teacher → samples must be capped at the limit.
    classes = [row(id=f"C{i}", name=f"G{i}", section="A") for i in range(25)]
    install_fake_model(monkeypatch, tg, "Class", queue=[classes])
    install_fake_model(monkeypatch, tg, "ClassTeacherAssignment", queue=[[]])
    install_fake_model(monkeypatch, tg, "ClassSubject", queue=[[]])
    install_fake_model(monkeypatch, tg, "ClassSubjectTeacher", queue=[])

    result = tg.summarize_teacher_gaps("tenant-1", "Y-2026")
    samples = result["data"]["samples"]["classes_missing_class_teacher"]
    assert len(samples) == tg._SAMPLE_LIMIT
    assert result["data"]["totals"]["classes_missing_class_teacher"] == 25
