"""Platform routes exposing the board subject templates.

The form needs two things: which boards exist, and what a board expands to for a
chosen grade range. Both read-only.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


@pytest.fixture(autouse=True)
def _app_context(flask_app):
    """error_response() builds a Flask response and needs an app context.

    Without this, the error-path tests pass only when an earlier test file has
    run: conftest's session-scoped `_db_engine` pushes a context and never pops
    it. That exact omission made an earlier test file depend on alphabetical
    file ordering.
    """
    with flask_app.app_context():
        yield


def _patch_body(monkeypatch, body):
    from modules.platform import routes

    monkeypatch.setattr(
        routes, "request", SimpleNamespace(get_json=lambda silent=False: body)
    )
    return routes


def test_rejects_a_missing_board_code(monkeypatch):
    routes = _patch_body(monkeypatch, {})
    payload, err = routes._parse_resolve_payload()
    assert payload is None
    assert err is not None


def test_rejects_a_missing_programme_code(monkeypatch):
    routes = _patch_body(monkeypatch, {"board_code": "gseb_gujarati", "grades": [1]})
    payload, err = routes._parse_resolve_payload()
    assert payload is None
    assert err is not None


def test_rejects_non_integer_grades(monkeypatch):
    routes = _patch_body(
        monkeypatch,
        {
            "board_code": "gseb_gujarati",
            "programme_code": "GSEB-GUJ",
            "grades": ["one", "two"],
        },
    )
    payload, err = routes._parse_resolve_payload()
    assert payload is None
    assert err is not None


def test_rejects_an_empty_grade_list(monkeypatch):
    routes = _patch_body(
        monkeypatch,
        {"board_code": "gseb_gujarati", "programme_code": "GSEB-GUJ", "grades": []},
    )
    payload, err = routes._parse_resolve_payload()
    assert payload is None
    assert err is not None


def test_accepts_a_valid_payload(monkeypatch):
    routes = _patch_body(
        monkeypatch,
        {
            "board_code": "gseb_gujarati",
            "programme_code": "GSEB-GUJ",
            "grades": [1, 2, 3],
            "stream": None,
        },
    )
    payload, err = routes._parse_resolve_payload()
    assert err is None
    assert payload == {
        "board_code": "gseb_gujarati",
        "programme_code": "GSEB-GUJ",
        "grades": [1, 2, 3],
        "stream": None,
    }


def test_grades_are_deduplicated_and_sorted(monkeypatch):
    """The form may submit a range with repeats; the resolver takes a set."""
    routes = _patch_body(
        monkeypatch,
        {
            "board_code": "gseb_gujarati",
            "programme_code": "GSEB-GUJ",
            "grades": [3, 1, 3, 2],
        },
    )
    payload, err = routes._parse_resolve_payload()
    assert err is None
    assert payload["grades"] == [1, 2, 3]
