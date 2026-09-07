"""What an integration can do, named so business code can ask for it.

A **capability** is the thing a feature wants — "send an SMS" — as opposed to
the vendor that happens to do it. This distinction is the whole point of the
module: a feature asks for `sms` and never learns which company carried it.

Deliberately a short list. A capability earns its place by having a caller,
not by being imaginable, and each one here is a contract somebody has to
implement.
"""

from __future__ import annotations

#: A short text message to a phone. The capability Phase 4's OTP will ask for.
CAPABILITY_SMS = "sms"

#: A message through WhatsApp. Not a second authentication method — the
#: method stays `mobile_otp`, and this is one of the wires it can go down.
#: Meta will not carry an authentication message except through a template
#: approved in advance, which is why `templates.py` exists.
CAPABILITY_WHATSAPP = "whatsapp"

CAPABILITIES = (CAPABILITY_SMS, CAPABILITY_WHATSAPP)

#: The capabilities that deliver a message to a person. Grouped because the
#: OTP channel choice ranges over exactly these, and a future capability that
#: is not a message — a payment, a lookup — must not silently become an
#: option on that menu.
MESSAGING_CAPABILITIES = (CAPABILITY_SMS, CAPABILITY_WHATSAPP)

#: Human labels for the platform screens.
CAPABILITY_LABELS = {
    CAPABILITY_SMS: "SMS",
    CAPABILITY_WHATSAPP: "WhatsApp",
}


# --- the life of a school's integration -------------------------------------
#
# Deliberately not a delete. Turning an integration off must leave the
# configuration, the usage history and the billing record intact — a school
# that pauses SMS over the summer has not lost its settings, and last term's
# messages still have to be explicable.

#: Configured, but not to be used for live work.
STATUS_DISABLED = "disabled"
#: Configured and selectable.
STATUS_ENABLED = "enabled"
#: Enabled, but the last attempt failed in a way that looks like configuration
#: rather than weather. Still stored, still not selected.
STATUS_FAILED = "failed"

STATUSES = (STATUS_DISABLED, STATUS_ENABLED, STATUS_FAILED)

#: The statuses a live operation may run under. `failed` is excluded on
#: purpose: an integration whose credentials were rejected should stop trying
#: until somebody looks at it, rather than burning a rate limit.
SELECTABLE_STATUSES = (STATUS_ENABLED,)
