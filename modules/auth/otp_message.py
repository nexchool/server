"""What the text message says.

Its own file so that changing the wording — for a template a provider has to
pre-register, for a second language, for a school that wants its name in it —
is not a change to the authentication logic.

The message is the one place the code exists in clear outside the sender's
memory. Nothing here logs it, and `modules/integrations/sms.py` deliberately
logs neither the body nor the number.
"""

from __future__ import annotations

from .otp import OTP_TTL_SECONDS


def build_otp_message(code: str) -> str:
    """The SMS a person receives.

    Short, no link, and it says what the code is for — the three things that
    make a code harder to phish. No school name and no personal detail: an SMS
    is readable on a locked screen by whoever is holding the phone.

    A real provider in India will require this text to match a template
    registered under the DLT regime before it can be sent at all; that
    registration belongs to the phase that selects a provider, and the wording
    here is what would be registered.
    """
    minutes = max(OTP_TTL_SECONDS // 60, 1)
    return (
        f"{code} is your NexSchool sign-in code. "
        f"It expires in {minutes} minutes. Do not share it with anyone."
    )
