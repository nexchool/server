"""MSG91's Flow API — the first real SMS vendor this build can talk to.

Written against `https://docs.msg91.com/reference/send-sms-flow` and
`https://api.msg91.com/apidoc/textsms/send-sms-flow.php`, read 2026-09-07.
MSG91 was picked for the reasons in the task-8 brief: domestic to India,
cheap, and it treats a DLT template as a first-class request parameter rather
than an afterthought — which is what India's Flow API actually enforces: a
send names a `flow_id` (a template MSG91 has itself DLT-registered) and fills
in that template's own variables, rather than accepting arbitrary text.

**Task 8 recorded that as a gap against `SmsProvider.send`'s contract; Task 8b
closed it.** The interface hands a provider a fully rendered `body` string,
and the Flow API has no field for one — the wording lives in the flow MSG91
already has on file. What it does take is a `variables` mapping, name to
value, and that mapping is not this client's to invent: `templates.py` lets a
school register a template as `{"id": ..., "variables": ["OTP", "MINUTES"]}`
— the flow's own variable names, in the order the calling code's positional
values arrive in — and `messaging.send_message` zips the two together and
refuses a count mismatch before any provider is ever called (see that
module). By the time `variables` reaches here, every key it contains is a
name the school's own flow declared, and this client's only job is to put
each one in the recipient object under that name. `body` is still accepted,
for interface conformance and because a bare-string template (no declared
variables) is still valid configuration, but it is never sent: there remains
no field in this API for free text, named-variable or not.

**No account exists and no DLT paperwork has been started.** This client
registers so the machinery around it (the registry, `capability_health`,
`set_integration_status`) is real, but `required_credentials` guarantees
`capability_health` reports it unconfigured and `set_integration_status`
refuses to enable it until `MSG91_AUTH_KEY` is set on the server — the same
gate every provider goes through, not a second mechanism invented for this
one.

`supports_idempotency` is `False`. The Flow API's documented parameters are
`flow_id`, `sender`, `recipients` (with `schtime` for scheduling and `short_url`
for link shortening) — nothing that lets a caller mark a request as a retry of
one already sent. That is what stops `messaging.py` from retrying a timed-out
send: MSG91 may already have accepted the first attempt, and a retry with no
way to say "this is the same request" would risk sending — and billing for —
the message twice.

`health()` never calls the network. There is no MSG91 account to verify a
balance check against yet, and even once there is one, MSG91's balance
endpoint (`GET /api/balance.php`) still costs a request against a real
account for a check this codebase runs on every integration listing — not
something to spend before it is needed. So this reports configuration
readiness only and leaves `provider_reachable` as `None`, which is what tells
an operator plainly that delivery was never verified.
"""

from __future__ import annotations

from typing import Optional

from .. import errors
from ..base import SmsProvider
from ..credentials import resolve_secret
from ..http import HttpResponse, post_json
from ..results import STATUS_ACCEPTED, MessageSendResult, ProviderHealth

#: MSG91's Flow API. HTTPS only — see `.claude/rules/forbidden-patterns.md`.
FLOW_ENDPOINT = "https://api.msg91.com/api/v5/flow/"

#: The environment variable this provider's secret lives in. Never stored,
#: never returned, never logged — see `credentials.py`.
AUTH_KEY_REFERENCE = "MSG91_AUTH_KEY"

#: HTTP status -> our normalized code. Order does not matter; `dict.get`
#: takes an exact match, and `_status_bucket` handles the 5xx range below.
_ERROR_CODES_BY_STATUS = {
    401: errors.AUTHENTICATION_ERROR,
    403: errors.AUTHENTICATION_ERROR,
    400: errors.VALIDATION_ERROR,
    422: errors.VALIDATION_ERROR,
    429: errors.RATE_LIMITED,
}


def _auth_key() -> Optional[str]:
    return resolve_secret(AUTH_KEY_REFERENCE)


def _error_code_for_status(status: int) -> str:
    if status in _ERROR_CODES_BY_STATUS:
        return _ERROR_CODES_BY_STATUS[status]
    if 500 <= status < 600:
        return errors.PROVIDER_UNAVAILABLE
    return errors.UNKNOWN_PROVIDER_ERROR


def _destination_for_msg91(destination: str) -> str:
    """MSG91 wants a bare international number, e.g. `919876543210` — no `+`."""
    return (destination or "").strip().lstrip("+")


def _normalize(response: HttpResponse, *, operation_id: Optional[str]) -> MessageSendResult:
    body = response.json()

    if response.status == 200 and body.get("type") == "success":
        return MessageSendResult(
            success=True,
            status=STATUS_ACCEPTED,
            provider_message_id=body.get("message"),
            provider_status=body.get("type"),
            operation_id=operation_id,
            billable_units=1,
        )

    code = _error_code_for_status(response.status)
    return MessageSendResult(
        success=False,
        error_code=code,
        # MSG91's own message ("unauthorized", "flow id missing", …). Never
        # the payload or a credential — just the vendor's stated reason.
        error_message=body.get("message") or "MSG91 rejected the request.",
        provider_status=body.get("type"),
        retryable=errors.is_retryable(code),
        operation_id=operation_id,
        billable_units=0,
    )


class Msg91Provider(SmsProvider):
    """MSG91's Flow API, for India-registered DLT templates."""

    key = "msg91"
    name = "MSG91"
    #: See the module docstring — the Flow API has no idempotency parameter.
    supports_idempotency = False
    required_credentials = (AUTH_KEY_REFERENCE,)

    def health(self, configuration: dict) -> ProviderHealth:
        credentials_present = bool(_auth_key())
        return ProviderHealth(
            configured=bool((configuration or {}).get("sender_id")),
            credentials_present=credentials_present,
            provider_supported=True,
            # Never verified by a live call — see the module docstring.
            provider_reachable=None,
            detail=(
                "Configuration readiness only; MSG91 was not contacted."
                if credentials_present
                else f"{AUTH_KEY_REFERENCE} is not set on this server."
            ),
        )

    def send(
        self,
        *,
        destination: str,
        body: str,
        template_id: Optional[str],
        configuration: dict,
        variables: dict,
        idempotency_key: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> MessageSendResult:
        auth_key = _auth_key()
        if not auth_key:
            return MessageSendResult(
                success=False,
                error_code=errors.CONFIGURATION_ERROR,
                error_message=f"{AUTH_KEY_REFERENCE} is not set on this server.",
                retryable=False,
                operation_id=operation_id,
                billable_units=0,
            )

        # `idempotency_key` is accepted for interface conformance and dropped:
        # the Flow API has no parameter for it (see `supports_idempotency`).
        # `body` is likewise accepted and dropped — see the module docstring.
        # Each entry in `variables` is forwarded verbatim under its own name;
        # `messaging.send_message` already proved it matches the school's
        # registered flow, so there is nothing here to validate again.
        recipient = {"mobiles": _destination_for_msg91(destination)}
        recipient.update(variables or {})
        payload = {
            "flow_id": template_id,
            "sender": (configuration or {}).get("sender_id"),
            "recipients": [recipient],
        }

        response, error_code = post_json(
            FLOW_ENDPOINT,
            payload,
            headers={"authkey": auth_key},
        )
        if response is None:
            return MessageSendResult(
                success=False,
                error_code=error_code,
                error_message="The request to MSG91 did not complete.",
                retryable=errors.is_retryable(error_code),
                operation_id=operation_id,
                billable_units=0,
            )

        return _normalize(response, operation_id=operation_id)
