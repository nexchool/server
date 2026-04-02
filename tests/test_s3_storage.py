"""Tests for S3 key helpers and stored reference parsing (no AWS calls)."""

from __future__ import annotations

import pytest
from flask import Flask

from backend.shared.s3_utils import (
    build_s3_key,
    get_env_prefix,
    is_external_url,
    key_for_s3_operation,
    normalize_stored_file_value_for_db,
    sanitize_filename,
    sanitize_folder,
)


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config.update(
        AWS_S3_BUCKET_NAME="my-bucket",
        AWS_REGION="ap-south-1",
        S3_ENV_PREFIX="prod",
    )
    return app


def test_get_env_prefix(app):
    with app.app_context():
        assert get_env_prefix() == "prod"


def test_build_s3_key_shape(app):
    with app.app_context():
        k = build_s3_key("students/documents", "photo.png")
        assert k.startswith("prod/students/documents/")
        assert "photo" in k or ".png" in k
        parts = k.split("/")
        assert len(parts) >= 4
        assert parts[0] == "prod"


def test_sanitize_filename_traversal():
    assert ".." not in sanitize_filename("../../../etc/passwd")
    assert sanitize_filename("x/y/z.txt").endswith(".txt")


def test_sanitize_folder():
    assert sanitize_folder("a/../b") == "a/b"
    assert sanitize_folder("") == ""


def test_key_for_s3_url_virtual_hosted(app):
    with app.app_context():
        url = "https://my-bucket.s3.ap-south-1.amazonaws.com/prod/students/a.pdf"
        assert key_for_s3_operation(url) == "prod/students/a.pdf"


def test_key_for_plain_key(app):
    with app.app_context():
        assert key_for_s3_operation("prod/students/a.pdf") == "prod/students/a.pdf"


def test_normalize_db_value(app):
    with app.app_context():
        url = "https://my-bucket.s3.ap-south-1.amazonaws.com/prod/teachers/x.png"
        assert normalize_stored_file_value_for_db(url) == "prod/teachers/x.png"
        assert normalize_stored_file_value_for_db("https://other.example.com/a.png") == "https://other.example.com/a.png"


def test_is_external(app):
    with app.app_context():
        assert is_external_url("https://res.cloudinary.com/foo/image/upload/v1/x.png")
        assert not is_external_url("prod/students/x.pdf")
