"""The MSG91 client, against a mocked transport. Nothing here reaches a network."""

from unittest.mock import patch

from modules.integrations import errors
from modules.integrations.http import HttpResponse
from modules.integrations.providers.msg91 import Msg91Provider


def _ok(body='{"type":"success","message":"abc123"}'):
    return HttpResponse(200, body, {}), None


def test_the_dlt_template_id_is_sent(monkeypatch):
    monkeypatch.setenv("MSG91_AUTH_KEY", "test-key")
    captured = {}

    def fake_post(url, payload, headers=None, timeout=15):
        captured["payload"] = payload
        return _ok()

    with patch("modules.integrations.providers.msg91.post_json", fake_post):
        Msg91Provider().send(
            destination="+919876543210",
            body="418302 is your NexSchool sign-in code.",
            template_id="1707169900000000000",
            configuration={"sender_id": "NEXSCH"},
        )

    assert "1707169900000000000" in str(captured["payload"])


def test_a_missing_credential_is_a_configuration_error_not_a_crash(monkeypatch):
    monkeypatch.delenv("MSG91_AUTH_KEY", raising=False)
    result = Msg91Provider().send(
        destination="+919876543210", body="x", template_id="t",
        configuration={"sender_id": "NEXSCH"},
    )
    assert result.success is False
    assert result.error_code == errors.CONFIGURATION_ERROR


def test_a_rejected_credential_is_normalized(monkeypatch):
    monkeypatch.setenv("MSG91_AUTH_KEY", "wrong")
    with patch(
        "modules.integrations.providers.msg91.post_json",
        lambda *a, **k: (HttpResponse(401, '{"message":"unauthorized"}', {}), None),
    ):
        result = Msg91Provider().send(
            destination="+919876543210", body="x", template_id="t",
            configuration={"sender_id": "NEXSCH"},
        )
    assert result.error_code == errors.AUTHENTICATION_ERROR
    assert result.retryable is False


def test_a_timeout_is_not_retryable_because_the_message_may_have_gone(monkeypatch):
    monkeypatch.setenv("MSG91_AUTH_KEY", "test-key")
    with patch(
        "modules.integrations.providers.msg91.post_json",
        lambda *a, **k: (None, errors.TIMEOUT),
    ):
        result = Msg91Provider().send(
            destination="+919876543210", body="x", template_id="t",
            configuration={"sender_id": "NEXSCH"},
        )
    assert result.error_code == errors.TIMEOUT
    assert result.retryable is False


def test_health_sends_nothing(monkeypatch):
    monkeypatch.setenv("MSG91_AUTH_KEY", "test-key")
    with patch("modules.integrations.providers.msg91.post_json") as posted:
        report = Msg91Provider().health({"sender_id": "NEXSCH"})
    posted.assert_not_called()
    assert report.provider_reachable is None


def test_it_does_not_claim_delivery(monkeypatch):
    """MSG91 acknowledges a request. That is `accepted`, never `delivered`."""
    monkeypatch.setenv("MSG91_AUTH_KEY", "test-key")
    with patch("modules.integrations.providers.msg91.post_json", lambda *a, **k: _ok()):
        result = Msg91Provider().send(
            destination="+919876543210", body="x", template_id="t",
            configuration={"sender_id": "NEXSCH"},
        )
    assert result.status == "accepted"
