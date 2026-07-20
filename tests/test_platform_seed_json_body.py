"""_parse_uploaded_config accepts a JSON body as well as a multipart upload.

`flask.request` is monkeypatched so no real request is needed, but the error
paths call error_response(), which builds a Flask response and therefore needs
an application context — hence the autouse fixture below.
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
    """Bind an application context for every test in this module.

    Without it these tests pass only when an earlier test file has already run:
    conftest's session-scoped `_db_engine` fixture pushes a context and never
    pops it, so the error-path tests silently inherit one. That made them
    dependent on alphabetical file ordering rather than on their own setup.
    """
    with flask_app.app_context():
        yield


def _patch_request(monkeypatch, *, is_json, json_body=None, files=None):
    from modules.platform import routes

    fake = SimpleNamespace(
        is_json=is_json,
        get_json=lambda silent=False: json_body,
        files=files or {},
    )
    monkeypatch.setattr(routes, "request", fake)
    return routes


def test_json_body_returns_the_config_dict(monkeypatch):
    routes = _patch_request(
        monkeypatch,
        is_json=True,
        json_body={"config": {"units": [{"code": "MN", "name": "Main"}]}},
    )
    config, err = routes._parse_uploaded_config()
    assert err is None
    assert config == {"units": [{"code": "MN", "name": "Main"}]}


def test_json_body_without_config_key_is_rejected(monkeypatch):
    routes = _patch_request(monkeypatch, is_json=True, json_body={})
    config, err = routes._parse_uploaded_config()
    assert config is None
    assert err is not None


def test_json_body_with_non_object_config_is_rejected(monkeypatch):
    routes = _patch_request(
        monkeypatch, is_json=True, json_body={"config": "not-an-object"}
    )
    config, err = routes._parse_uploaded_config()
    assert config is None
    assert err is not None


def test_multipart_path_still_works(monkeypatch):
    routes = _patch_request(
        monkeypatch,
        is_json=False,
        files={
            "file": SimpleNamespace(
                filename="school.json", read=lambda: b'{"units": []}'
            )
        },
    )
    config, err = routes._parse_uploaded_config()
    assert err is None
    assert config == {"units": []}


def test_missing_file_and_missing_json_is_rejected(monkeypatch):
    routes = _patch_request(monkeypatch, is_json=False, files={})
    config, err = routes._parse_uploaded_config()
    assert config is None
    assert err is not None
