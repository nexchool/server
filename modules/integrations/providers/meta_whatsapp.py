"""Meta's WhatsApp Cloud API — the second real vendor this build can talk to.

Written against Meta's own developer documentation, read 2026-09-07:

  * Messages endpoint & auth —
    https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages
    confirms `POST https://graph.facebook.com/v25.0/<PHONE_NUMBER_ID>/messages`
    with `Authorization: Bearer <ACCESS_TOKEN>`, and that a successful send's
    id is `messages[0].id`. (`v25.0` is what that page's own example uses
    today; the Graph API changelog lists `v26.0` as the newest version as of
    this read — both are live, and `GRAPH_VERSION` below is the one seam to
    touch when NexSchool moves onto the newer one.)
  * Template message body shape —
    https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
    confirms the `template` message envelope: `type: "template"`,
    `template.name`, `template.language.code`, and a `components` array
    whose `type: "body"` entry carries an ordered `parameters` list of
    `{"type": "text", "text": ...}`.
  * Authentication-category templates —
    https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/authentication-templates/authentication-templates
    and https://docs.360dialog.com/docs/resources/authentication-messages
    (cross-referenced because Meta's own page did not show a full send-time
    request body for this category). Both confirm authentication templates
    are not just a body with `{{1}}` for the code: they carry a **required**
    button component (`type: "button"`, `sub_type: "url"`, `index: 0`, one
    `{"type": "text", "text": <code>}` parameter) that a plain utility
    template does not have — a one-tap-autofill or copy-code button is
    mandatory in the template's own definition. **This client does not
    construct that button component.** `templates.py` — this codebase's only
    record of a school's registered template — carries an id and a tuple of
    ordered variable *names*; it has no concept of a template's button shape,
    and there is no Meta Business account or approved template yet to prove
    a guessed one against. Sending a body-only request against a template
    that requires a button will fail with a vendor-side validation error,
    surfaced here as `VALIDATION_ERROR` like any other malformed request —
    not silently. Adding button support is future work for whoever
    configures the first real authentication template, at which point there
    is a real template to test the shape against.
  * Error body shape —
    https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
    confirms `{"error": {"message", "type", "code", "error_data", "fbtrace_id"}}`.
    `error.code` is Meta's own numeric code (e.g. `190` for an invalid or
    expired token); this client keeps that as `provider_status` for support
    to read and never parses it into control flow — the HTTP status is what
    drives normalization, the same house pattern as `msg91.py`.

Two things the brief guessed at that the docs settle differently:

  * The brief's interface line says `required_credentials = ("access_token",)`.
    That name is a placeholder, not an environment variable — the actual
    reference, matching `env.example` and `credentials.py`'s naming
    convention, is `META_WHATSAPP_ACCESS_TOKEN`.
  * The access token has to be a **permanent system-user token** generated
    for a System User on the Meta Business account, not the 24-hour token
    the Cloud API quickstart hands out for testing. A 24-hour token expiring
    mid-production is an outage with no code change to fix it — it is a
    credential rotation nobody scheduled. `resolve_secret` cannot tell one
    kind of token from the other; this is an operational note for whoever
    provisions `META_WHATSAPP_ACCESS_TOKEN`, not something this file can
    enforce.

**No Meta Business account exists and no template has been approved.** This
client registers so the machinery around it (the registry, `capability_health`,
`set_integration_status`) is real, the same posture Task 8 took for MSG91:
`required_credentials` guarantees `capability_health` reports it unconfigured
and `set_integration_status` refuses to enable it until
`META_WHATSAPP_ACCESS_TOKEN` is set on the server.

The phone number id and the WhatsApp Business Account id are **identifiers,
not secrets** — they select which of Meta's resources a send talks to, they
say nothing an attacker could use without the token, and a school's
integration `configuration` is exactly where an identifier belongs (see
`credentials.py`'s split). Only the phone number id is actually needed to
send (it is the URL's own path segment); the business account id has no use
in this client yet and is not read here, but both live on `configuration`
together because that is the natural place for whoever configures the
account to record both. A `configuration` with no `phone_number_id` fails
as `CONFIGURATION_ERROR` before any network call, the same as a missing
credential — there is no vendor endpoint to call without one.

`supports_idempotency` is `False`. The Cloud API's `/messages` endpoint
documents no idempotency-key parameter; a retried POST is a second, separate
send. That is what keeps `messaging.py` from retrying a timed-out WhatsApp
send — Meta may already have accepted the first attempt.

`health()` never calls the network, for the same reason `msg91.py` gives:
there is no account to check against yet, and even once there is one, a
metadata call spent on every integration listing is not free of cost or of
risk to whatever rate limit a school's WhatsApp Business Account carries.
This reports configuration readiness only and leaves `provider_reachable` as
`None`.
"""

from __future__ import annotations

from typing import Optional

from .. import errors
from ..base import WhatsAppProvider
from ..credentials import resolve_secret
from ..http import HttpResponse, post_json
from ..results import STATUS_ACCEPTED, MessageSendResult, ProviderHealth

#: Meta's Graph API root. HTTPS only — see `.claude/rules/forbidden-patterns.md`.
GRAPH_BASE_URL = "https://graph.facebook.com"

#: The version this client is written against — see the module docstring for
#: where that was read and how to move it forward.
GRAPH_VERSION = "v25.0"

#: Used when a school's configuration names no language for its template.
#: Meta requires a language code on every template send; English is this
#: build's only shipped copy so far (see the OTP templates task-8 assumed).
DEFAULT_LANGUAGE_CODE = "en"

#: The environment variable this provider's secret lives in. Never stored,
#: never returned, never logged — see `credentials.py`.
ACCESS_TOKEN_REFERENCE = "META_WHATSAPP_ACCESS_TOKEN"

#: HTTP status -> our normalized code. Order does not matter; `dict.get`
#: takes an exact match, and `_status_bucket` handles the 5xx range below.
_ERROR_CODES_BY_STATUS = {
    401: errors.AUTHENTICATION_ERROR,
    403: errors.AUTHENTICATION_ERROR,
    400: errors.VALIDATION_ERROR,
    404: errors.VALIDATION_ERROR,
    429: errors.RATE_LIMITED,
}


def _access_token() -> Optional[str]:
    return resolve_secret(ACCESS_TOKEN_REFERENCE)


def _error_code_for_status(status: int) -> str:
    if status in _ERROR_CODES_BY_STATUS:
        return _ERROR_CODES_BY_STATUS[status]
    if 500 <= status < 600:
        return errors.PROVIDER_UNAVAILABLE
    return errors.UNKNOWN_PROVIDER_ERROR


def _destination_for_whatsapp(destination: str) -> str:
    """Meta wants a bare international number, e.g. `919876543210` — no `+`."""
    return (destination or "").strip().lstrip("+")


def _normalize(response: HttpResponse, *, operation_id: Optional[str]) -> MessageSendResult:
    body = response.json()

    if response.status == 200 and body.get("messages"):
        message = (body.get("messages") or [{}])[0]
        return MessageSendResult(
            success=True,
            status=STATUS_ACCEPTED,
            provider_message_id=message.get("id"),
            # Meta's own per-message pacing status, when it sends one — kept
            # for support to read, never parsed.
            provider_status=message.get("message_status"),
            operation_id=operation_id,
            billable_units=1,
        )

    error = body.get("error") or {}
    code = _error_code_for_status(response.status)
    return MessageSendResult(
        success=False,
        error_code=code,
        # Meta's own message ("Invalid OAuth access token", …). Never the
        # payload or a credential — just the vendor's stated reason.
        error_message=error.get("message") or "Meta rejected the request.",
        # Meta's numeric error code (e.g. 190), kept as a string for support
        # to read against Meta's own error-code reference. Never parsed.
        provider_status=str(error["code"]) if "code" in error else None,
        retryable=errors.is_retryable(code),
        operation_id=operation_id,
        billable_units=0,
    )


class MetaWhatsAppProvider(WhatsAppProvider):
    """Meta's WhatsApp Cloud API — authentication messages, template only."""

    key = "meta_whatsapp"
    name = "WhatsApp (Meta Cloud API)"
    #: See the module docstring — the Cloud API's `/messages` endpoint has no
    #: idempotency parameter.
    supports_idempotency = False
    required_credentials = (ACCESS_TOKEN_REFERENCE,)

    def health(self, configuration: dict) -> ProviderHealth:
        credentials_present = bool(_access_token())
        configured = bool((configuration or {}).get("phone_number_id"))
        return ProviderHealth(
            configured=configured,
            credentials_present=credentials_present,
            provider_supported=True,
            # Never verified by a live call — see the module docstring.
            provider_reachable=None,
            detail=(
                "Configuration readiness only; Meta was not contacted."
                if credentials_present
                else f"{ACCESS_TOKEN_REFERENCE} is not set on this server."
            ),
        )

    def send(
        self,
        *,
        destination: str,
        template_name: str,
        variables: "list[str]",
        configuration: dict,
        idempotency_key: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> MessageSendResult:
        access_token = _access_token()
        if not access_token:
            return MessageSendResult(
                success=False,
                error_code=errors.CONFIGURATION_ERROR,
                error_message=f"{ACCESS_TOKEN_REFERENCE} is not set on this server.",
                retryable=False,
                operation_id=operation_id,
                billable_units=0,
            )

        configuration = configuration or {}
        phone_number_id = configuration.get("phone_number_id")
        if not phone_number_id:
            # An identifier, not a secret — see the module docstring — but
            # still required: it is the URL's own path segment, and there is
            # no vendor endpoint to call without it.
            return MessageSendResult(
                success=False,
                error_code=errors.CONFIGURATION_ERROR,
                error_message=(
                    "This school's WhatsApp integration has no phone_number_id "
                    "configured."
                ),
                retryable=False,
                operation_id=operation_id,
                billable_units=0,
            )

        language = configuration.get("language") or DEFAULT_LANGUAGE_CODE

        # `idempotency_key` is accepted for interface conformance and
        # dropped — see `supports_idempotency` above. `variables` is
        # forwarded positionally, one per body slot, in the order the
        # template declares them: see `WhatsAppProvider.send`'s docstring
        # for why this is a list and not a mapping.
        payload = {
            "messaging_product": "whatsapp",
            "to": _destination_for_whatsapp(destination),
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": value}
                            for value in (variables or [])
                        ],
                    }
                ],
            },
        }

        url = f"{GRAPH_BASE_URL}/{GRAPH_VERSION}/{phone_number_id}/messages"
        response, error_code = post_json(
            url,
            payload,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response is None:
            return MessageSendResult(
                success=False,
                error_code=error_code,
                error_message="The request to Meta did not complete.",
                retryable=errors.is_retryable(error_code),
                operation_id=operation_id,
                billable_units=0,
            )

        return _normalize(response, operation_id=operation_id)
