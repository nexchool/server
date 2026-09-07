"""The Meta WhatsApp Cloud API client, against a mocked transport.

Nothing here reaches a network — see `test_provider_msg91.py`, which this
file mirrors. The one structural difference is `test_the_variables_are_sent_
positionally`: WhatsApp's `variables` is an ordered list, not a name -> value
mapping, because a template's slot order belongs to the template and not to
NexSchool (see `modules/integrations/base.py::WhatsAppProvider.send`).
"""

from unittest.mock import patch

from modules.integrations import errors
from modules.integrations.http import HttpResponse
from modules.integrations.providers.meta_whatsapp import MetaWhatsAppProvider


def _ok(message_id="wamid.HBgL"):
    body = '{"messaging_product":"whatsapp","messages":[{"id":"%s"}]}' % message_id
    return HttpResponse(200, body, {}), None


def test_the_variables_are_sent_positionally(monkeypatch):
    """A template's slots are ordered by the template, not by us."""
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "test-token")
    captured = {}

    def fake_post(url, payload, headers=None, timeout=15):
        captured["payload"] = payload
        captured["url"] = url
        captured["headers"] = headers
        return HttpResponse(200, '{"messages":[{"id":"wamid.X"}]}', {}), None

    with patch("modules.integrations.providers.meta_whatsapp.post_json", fake_post):
        MetaWhatsAppProvider().send(
            destination="+919876543210",
            template_name="nexschool_login_code",
            variables=["418302", "5"],
            configuration={"phone_number_id": "123456", "language": "en"},
        )

    body = captured["payload"]
    assert body["type"] == "template"
    assert body["template"]["name"] == "nexschool_login_code"
    parameters = body["template"]["components"][0]["parameters"]
    assert [p["text"] for p in parameters] == ["418302", "5"]
    assert "123456" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer test-token"


def test_a_missing_phone_number_id_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "test-token")
    result = MetaWhatsAppProvider().send(
        destination="+919876543210", template_name="t", variables=[],
        configuration={},
    )
    assert result.success is False
    assert result.error_code == errors.CONFIGURATION_ERROR


def test_a_missing_credential_is_a_configuration_error_not_a_crash(monkeypatch):
    monkeypatch.delenv("META_WHATSAPP_ACCESS_TOKEN", raising=False)
    result = MetaWhatsAppProvider().send(
        destination="+919876543210", template_name="t", variables=[],
        configuration={"phone_number_id": "123456"},
    )
    assert result.success is False
    assert result.error_code == errors.CONFIGURATION_ERROR


def test_a_rejected_credential_is_normalized(monkeypatch):
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "wrong")
    body = (
        '{"error":{"message":"Invalid OAuth access token","type":"OAuthException",'
        '"code":190,"fbtrace_id":"abc123"}}'
    )
    with patch(
        "modules.integrations.providers.meta_whatsapp.post_json",
        lambda *a, **k: (HttpResponse(401, body, {}), None),
    ):
        result = MetaWhatsAppProvider().send(
            destination="+919876543210", template_name="t", variables=[],
            configuration={"phone_number_id": "123456"},
        )
    assert result.error_code == errors.AUTHENTICATION_ERROR
    assert result.retryable is False


def test_a_timeout_is_not_retryable_because_the_message_may_have_gone(monkeypatch):
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "test-token")
    with patch(
        "modules.integrations.providers.meta_whatsapp.post_json",
        lambda *a, **k: (None, errors.TIMEOUT),
    ):
        result = MetaWhatsAppProvider().send(
            destination="+919876543210", template_name="t", variables=[],
            configuration={"phone_number_id": "123456"},
        )
    assert result.error_code == errors.TIMEOUT
    assert result.retryable is False


def test_health_sends_nothing(monkeypatch):
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "test-token")
    with patch("modules.integrations.providers.meta_whatsapp.post_json") as posted:
        report = MetaWhatsAppProvider().health({"phone_number_id": "123456"})
    posted.assert_not_called()
    assert report.provider_reachable is None


def test_it_does_not_claim_delivery(monkeypatch):
    """Meta acknowledges a request. That is `accepted`, never `delivered`."""
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "test-token")
    with patch("modules.integrations.providers.meta_whatsapp.post_json", lambda *a, **k: _ok()):
        result = MetaWhatsAppProvider().send(
            destination="+919876543210", template_name="t", variables=["418302"],
            configuration={"phone_number_id": "123456"},
        )
    assert result.status == "accepted"
    assert result.provider_message_id == "wamid.HBgL"


def test_supports_idempotency_is_honestly_false():
    """The Cloud API's messages endpoint has no idempotency-key parameter — a
    retried request is a second send, not a safe no-op."""
    assert MetaWhatsAppProvider.supports_idempotency is False


def test_required_credentials_names_the_access_token_only():
    """The phone number id and business account id are identifiers, not
    secrets — see the module docstring — so only the token gates enablement."""
    assert MetaWhatsAppProvider.required_credentials == ("META_WHATSAPP_ACCESS_TOKEN",)
