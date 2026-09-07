"""Which registered template carries a message, and what goes in its slots.

Both channels this build supports refuse free text.

Under India's DLT regime an SMS is delivered only when its body matches a
template registered against the sender's entity, and the send carries that
template's id. Meta will not send an authentication-category WhatsApp
message except through a template approved in advance, and there the send
carries the template's *name* plus its variables positionally — no body at
all.

So a message here is a **purpose** — what it is for — plus the values that
go in its slots. Which template serves a purpose is per-school, per-channel
configuration, stored on the integration row because it is an identifier and
not a secret, and because two schools sharing one vendor account may well
have registered different wordings.

The rendered text has not gone away: it is what an operator submits for
approval, and it is what the fake providers put in the outbox so a developer
reads the real wording. It is simply no longer what is sent.
"""

from __future__ import annotations

from .errors import TEMPLATE_NOT_CONFIGURED, IntegrationError

#: A sign-in code. The only purpose this phase has; each new one is a
#: separate registration with each vendor and so earns its own constant.
PURPOSE_LOGIN_OTP = "login_otp"

#: Where the map lives on an integration's `configuration`.
TEMPLATES_KEY = "templates"


def template_for(configuration: dict, purpose: str) -> str:
    """The template this school registered for this purpose.

    Raises rather than returning None. A send that reached a provider without
    a template would be refused by the vendor with a code somebody has to
    look up, and would count against a rate limit on the way; refusing here
    costs nothing and says exactly what is missing.
    """
    registered = (configuration or {}).get(TEMPLATES_KEY) or {}
    template = registered.get(purpose)
    if not template:
        raise IntegrationError(
            TEMPLATE_NOT_CONFIGURED,
            f"This school has no template registered for '{purpose}'.",
        )
    return str(template)
