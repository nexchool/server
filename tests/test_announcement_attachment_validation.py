"""An announcement attachment is a file a school sends to every parent.

`create_attachment` validated nothing. The route handed it
`file.content_type` — a header the client writes — and that value was stored
**and used as the S3 object's own `ContentType`**, so an uploader chose how
the object would later be served. `size_bytes` came from
`file.content_length`, which multipart uploads usually leave at 0, and was
only recorded, never enforced; the sole ceiling was the global 64 MB request
limit shared with every other endpoint.

`modules/documents/service.py` already does this correctly — allowlist the
type, measure the stream rather than believe a declared length, refuse empty
and oversize, and store the *normalised* type. This brings the same rules
here, with an allowlist suited to what a school actually attaches to a notice.
"""

from __future__ import annotations

import io

import pytest
from flask import g

from modules.announcements import services


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def uploader(db_session, tenant):
    from modules.auth.models import User

    import uuid
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Office",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _attach(uploader, *, data=b"%PDF-1.4 a notice", filename="notice.pdf",
            content_type="application/pdf"):
    return services.create_attachment(
        actor_user_id=uploader.id,
        file_stream=io.BytesIO(data),
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
    )


# ---------------------------------------------------------------------------
# The type the uploader declares
# ---------------------------------------------------------------------------

def test_a_dangerous_type_is_refused(ctx, uploader):
    """The declared type becomes the S3 object's, so it decides how it serves.

    `text/html` stored as html and later opened from a presigned URL is script
    running against whatever that URL's origin can reach.
    """
    with pytest.raises(services.ValidationError):
        _attach(
            uploader,
            data=b"<script>alert(1)</script>",
            filename="notice.html",
            content_type="text/html",
        )


def test_svg_is_refused(ctx, uploader):
    """An image type that can carry script is not an image for this purpose."""
    with pytest.raises(services.ValidationError):
        _attach(
            uploader,
            data=b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>",
            filename="logo.svg",
            content_type="image/svg+xml",
        )


def test_an_unknown_type_is_refused(ctx, uploader):
    with pytest.raises(services.ValidationError):
        _attach(uploader, data=b"MZ\x90", filename="setup.exe",
                content_type="application/x-msdownload")


def test_an_undeclared_type_falls_back_to_the_filename(ctx, uploader):
    """Expo sends `application/octet-stream` whenever it cannot name the type.

    Both clients pick with no filter, so an ordinary PDF arrives unlabelled.
    Refusing it would be the wrong answer; the name is enough to infer from,
    and the inferred type still has to clear the allowlist.
    """
    attachment = _attach(uploader, filename="notice.pdf",
                         content_type="application/octet-stream")

    assert attachment.content_type == "application/pdf"


def test_an_undeclared_type_with_a_dangerous_name_is_still_refused(ctx, uploader):
    """The fallback infers; it does not wave things through."""
    with pytest.raises(services.ValidationError):
        _attach(uploader, data=b"<script>alert(1)</script>",
                filename="notice.html",
                content_type="application/octet-stream")


def test_an_undeclared_type_with_no_extension_is_refused(ctx, uploader):
    with pytest.raises(services.ValidationError):
        _attach(uploader, filename="notice",
                content_type="application/octet-stream")


def test_the_type_is_matched_regardless_of_case_and_padding(ctx, uploader):
    attachment = _attach(uploader, content_type="  APPLICATION/PDF ")

    assert attachment.content_type == "application/pdf", (
        "the normalised type must be what is stored and sent to S3"
    )


# ---------------------------------------------------------------------------
# The size the uploader declares
# ---------------------------------------------------------------------------

def test_an_empty_file_is_refused(ctx, uploader):
    with pytest.raises(services.ValidationError):
        _attach(uploader, data=b"")


def test_a_file_over_the_limit_is_refused(ctx, uploader):
    oversize = b"%PDF-1.4" + b"\0" * services.MAX_ATTACHMENT_BYTES

    with pytest.raises(services.ValidationError):
        _attach(uploader, data=oversize)


def test_the_recorded_size_is_measured_not_believed(ctx, uploader):
    """`content_length` is 0 on most multipart uploads and client-set anyway."""
    data = b"%PDF-1.4 a notice"

    attachment = services.create_attachment(
        actor_user_id=uploader.id,
        file_stream=io.BytesIO(data),
        filename="notice.pdf",
        content_type="application/pdf",
        size_bytes=999_999,  # a lie, and the shape the route actually sends
    )

    assert attachment.size_bytes == len(data)


def test_an_ordinary_notice_still_uploads(ctx, uploader):
    attachment = _attach(uploader)

    assert attachment.content_type == "application/pdf"
    assert attachment.size_bytes > 0
    assert attachment.s3_key
