"""Which registered template carries a message, and what goes in its slots.

Both channels this build supports refuse free text.

Under India's DLT regime an SMS is delivered only when it goes through a
template registered against the sender's entity. Task 8 found that this is
not one shape: MSG91's Flow API has no field for message text at all — the
wording lives in a flow registered on their dashboard, and a send supplies
values for that flow's own **named** variables (`##OTP##`, `##MINUTES##`).
Meta's WhatsApp templates take their variables **positionally** instead — an
ordered list, no names anywhere. A bare template id said enough for a vendor
that only needed a DLT stamp; it says nothing about which value goes in
which of a flow's named slots.

So a template entry here is `MessageTemplate(id, variables)` — a vendor id
plus the names of the slots it exposes, in the order a positional caller
should fill them. `variables` defaults to empty, which is what a **bare
string** configuration means: every existing row and test fixture holds one
of these, registered before Task 8b existed, and none of them stop working —
they simply carry no names, which is correct for a channel that does not
need any (WhatsApp, which is positional and ignores names entirely) and
refused at the send layer for one that does (`messaging.send_message`, for
SMS — see that module for why a count mismatch is caught before a provider
is ever called).

Which template serves a purpose is per-school, per-channel configuration,
stored on the integration row because it is an identifier and not a secret,
and because two schools sharing one vendor account may well have registered
different wordings.

The rendered text has not gone away: it is what an operator submits for
approval, and it is what the fake providers put in the outbox so a developer
reads the real wording. It is simply no longer what is sent to a
variable-driven vendor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .errors import TEMPLATE_NOT_CONFIGURED, IntegrationError

#: No OTP purpose constant lives here. `otp_models.PURPOSE_AUTHENTICATION`
#: already owns that concept — it is a stored column value with a server
#: default and a challenge-lookup filter, and it is what `otp.py` passes to
#: `send_sms` as both the template key and the usage ledger's `usage_type`.
#: A second name for the same string would be a second owner of it, and the
#: two would eventually drift. Callers pass the purpose they already own;
#: this module only does the lookup.

#: Where the map lives on an integration's `configuration`.
TEMPLATES_KEY = "templates"


@dataclass(frozen=True)
class MessageTemplate:
    """A vendor template id, and the names of the slots it exposes.

    Frozen because this is a lookup result, not something a caller should be
    able to mutate on its way from `template_for` to a provider's `send`.
    `variables` is a tuple, not a list, for the same reason — and because it
    is what gets zipped against a positional values list, where order is the
    entire point.
    """

    id: str
    variables: Tuple[str, ...] = ()


def template_for(configuration: dict, purpose: str) -> MessageTemplate:
    """The template this school registered for this purpose.

    Raises rather than returning None. A send that reached a provider without
    a template would be refused by the vendor with a code somebody has to
    look up, and would count against a rate limit on the way; refusing here
    costs nothing and says exactly what is missing.

    Normalizes both configuration shapes a school's row can hold: a bare
    string (`"1707169900000000000"`) — the only shape that existed before
    Task 8b, still valid, and always resolved with no names — and an object
    (`{"id": ..., "variables": [...]}`) for a vendor whose template has named
    slots. Either way the caller gets one type back and never has to branch
    on which shape a school happened to save.
    """
    registered = (configuration or {}).get(TEMPLATES_KEY) or {}
    entry = registered.get(purpose)
    if not entry:
        raise IntegrationError(
            TEMPLATE_NOT_CONFIGURED,
            f"This school has no template registered for '{purpose}'.",
        )

    if isinstance(entry, dict):
        template_id = entry.get("id")
        if not template_id:
            raise IntegrationError(
                TEMPLATE_NOT_CONFIGURED,
                f"This school's '{purpose}' template has no id.",
            )
        return MessageTemplate(
            id=str(template_id),
            variables=tuple(entry.get("variables") or ()),
        )

    return MessageTemplate(id=str(entry), variables=())
