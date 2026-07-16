"""Tests for scripts/subject_catalogue_to_yaml.py — pure-Python, no DB."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from scripts.subject_catalogue_to_yaml import (  # noqa: E402
    CatalogueError,
    build_sections,
    render_yaml,
)


def _catalogue(**overrides):
    base = {
        "programmes": [
            {
                "code": "GSEB-GUJ",
                "catalogue": [
                    {"code": "12", "name": "Mathematics", "role": "core", "short_code": "MATH"},
                    {"code": "01", "name": "Gujarati", "role": "first_language"},
                ],
                "standards": [
                    {
                        "grade": "1",
                        "subjects": [
                            {"code": "12", "weekly": 6},
                            {"code": "01", "weekly": 6, "type": "mandatory"},
                        ],
                    }
                ],
            }
        ]
    }
    base.update(overrides)
    return base


def test_builds_deduped_subjects_and_offerings():
    sections = build_sections(_catalogue())

    assert [s["code"] for s in sections["subjects"]] == ["01", "12"]
    assert sections["subjects"][1] == {
        "code": "12",
        "name": "Mathematics",
        "role": "core",
        "short_code": "MATH",
    }
    assert sections["offerings"] == [
        {
            "programme": "GSEB-GUJ",
            "grade": "1",
            "subjects": [
                {"code": "12", "weekly": 6, "type": "mandatory"},
                {"code": "01", "weekly": 6, "type": "mandatory"},
            ],
        }
    ]


def test_shared_subject_across_programmes_is_deduped():
    data = _catalogue()
    data["programmes"].append(
        {
            "code": "CBSE-ENG",
            "catalogue": [
                {"code": "12", "name": "Mathematics", "role": "core", "short_code": "MATH"},
            ],
            "standards": [
                {"grade": "1", "subjects": [{"code": "12", "weekly": 5}]}
            ],
        }
    )
    sections = build_sections(data)
    assert [s["code"] for s in sections["subjects"]] == ["01", "12"]
    assert len(sections["offerings"]) == 2


def test_conflicting_subject_definition_fails():
    data = _catalogue()
    data["programmes"].append(
        {
            "code": "CBSE-ENG",
            "catalogue": [{"code": "12", "name": "Maths (Std)"}],
            "standards": [
                {"grade": "1", "subjects": [{"code": "12", "weekly": 5}]}
            ],
        }
    )
    with pytest.raises(CatalogueError, match="defined differently"):
        build_sections(data)


def test_undeclared_offering_code_fails():
    data = _catalogue()
    data["programmes"][0]["standards"][0]["subjects"].append({"code": "GHOST"})
    with pytest.raises(CatalogueError, match="not declared"):
        build_sections(data)


def test_missing_standards_fails():
    data = _catalogue()
    data["programmes"][0]["standards"] = []
    with pytest.raises(CatalogueError, match="no standards"):
        build_sections(data)


def test_offering_defaults_weekly_and_type():
    data = _catalogue()
    data["programmes"][0]["standards"][0]["subjects"] = [{"code": "12"}]
    sections = build_sections(data)
    assert sections["offerings"][0]["subjects"] == [
        {"code": "12", "weekly": 5, "type": "mandatory"}
    ]


def test_render_yaml_quotes_codes_and_keeps_numbers():
    out = render_yaml(build_sections(_catalogue()))
    assert 'code: "12"' in out          # quoted — leading zeros survive
    assert "weekly: 6" in out           # numbers stay unquoted
    assert out.startswith("subjects:\n")
    assert "offerings:" in out
