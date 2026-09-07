"""What a PIN is allowed to be, and how one is made.

A PIN is a password with most of its strength removed on purpose. Six digits
is a million values, against a password's trillions — a child has to be able
to remember it and type it on a phone, and that convenience is the whole point
of the method.

So the security has to come from somewhere else, and this file is honest about
where: **not from the secret**. It comes from the online attempt limits in
`pin_throttle.py`. A million values falls to an offline attacker in seconds
and to an online one never, provided the online path counts. Everything here
assumes that counting works.

Two rules follow from the shortness:

**A PIN is a string, never a number.** `000123` is six digits. Parsed as an
integer it becomes `123`, which is a different, shorter secret — and one whose
hash would then match anybody who chose `123` in a system that allowed three
digits. Nothing in this module converts a PIN to `int`.

**Trivial PINs are refused.** Against a limited number of online guesses, an
attacker spends them on the handful of values people actually pick. Rejecting
those is worth more here than any amount of hashing.
"""

from __future__ import annotations

import secrets

#: Six digits. Long enough that the throttle has room to work, short enough
#: that a nine-year-old will not write it on the back of their hand.
#: One place, read by the generator, the validator, the API and the UI.
PIN_LENGTH = 6

#: A holder choosing their own PIN gets no latitude on length: a four-digit
#: PIN in a six-digit system is a hundredfold weaker and looks identical in a
#: database. Min and max are equal on purpose, and named separately so a later
#: product decision to allow a range has somewhere to land.
PIN_MIN_LENGTH = PIN_LENGTH
PIN_MAX_LENGTH = PIN_LENGTH


class WeakPin(Exception):
    """The PIN is valid in shape but too easy to guess."""


class InvalidPin(Exception):
    """The PIN is not the right shape to be a PIN at all."""


#: PINs refused outright.
#:
#: Deliberately short, and derived rather than collected: every one is either
#: all-one-digit, a run, or a repeated pair. A thousand-entry blacklist copied
#: from a breach corpus would refuse PINs nobody here would pick and would
#: still miss the next one; these are the patterns a person reaches for when
#: asked to invent six digits on the spot.
#:
#: Note what is *not* here. A PIN is not refused for resembling an admission
#: number or a date of birth. Checking that would mean reading the child's
#: record every time they set a PIN, and it would leak: an attacker who can
#: see which PINs are refused for one student learns something about that
#: student. The defence against a guessable-from-personal-data PIN is that the
#: school issues a random one; a holder who then chooses their own birthday is
#: making a choice this system is not in a position to second-guess.
def _trivial_pins(length: int) -> frozenset:
    trivial = set()

    for digit in "0123456789":
        trivial.add(digit * length)

    ascending = "01234567890123456789"
    descending = ascending[::-1]
    for run in (ascending, descending):
        for start in range(len(run) - length + 1):
            trivial.add(run[start : start + length])

    # Doubled runs: 112233, 445566, 332211. Not caught by the block rule
    # above, which sees three unequal pairs, and exactly the kind of thing
    # somebody invents when asked for six digits they will remember.
    for repeat in (2, 3):
        if length % repeat:
            continue
        span = length // repeat
        for run in (ascending, descending):
            for start in range(len(run) - span + 1):
                trivial.add("".join(d * repeat for d in run[start : start + span]))

    # Repeated short blocks: 123123, 121212, 111111.
    for block in (1, 2, 3):
        if length % block:
            continue
        for value in range(10 ** block):
            piece = f"{value:0{block}d}"
            trivial.add(piece * (length // block))

    return frozenset(pin for pin in trivial if len(pin) == length)


TRIVIAL_PINS = _trivial_pins(PIN_LENGTH)


def is_trivial(pin: str) -> bool:
    return pin in TRIVIAL_PINS


def validate_pin(pin: str) -> str:
    """The PIN, if it may be used. Raises otherwise.

    Returns the value rather than a boolean so that a caller cannot validate
    one string and store another — the checked value is the one that comes
    back.
    """
    if not isinstance(pin, str):
        raise InvalidPin("A PIN must be given as text, digit by digit.")

    candidate = pin.strip()
    if not candidate.isdigit():
        raise InvalidPin("A PIN is digits only.")
    if len(candidate) < PIN_MIN_LENGTH or len(candidate) > PIN_MAX_LENGTH:
        raise InvalidPin(f"A PIN is exactly {PIN_LENGTH} digits.")
    if is_trivial(candidate):
        raise WeakPin(
            "That PIN is too easy to guess. Avoid repeated digits and simple runs."
        )
    return candidate


def generate_pin(length: int = PIN_LENGTH) -> str:
    """A PIN that says nothing about the person it belongs to.

    `secrets.randbelow(10 ** length)` rather than `randbelow(...) % ...` or
    `random.randint` — the first is uniform by construction, the second has
    modulo bias, and the third is a Mersenne Twister whose next output can be
    predicted from its previous ones. The same device the OTP uses, for the
    same reasons.

    Zero-padded, so `000123` is as likely as any other value and every PIN is
    the same length. A generator that dropped leading zeros would quietly make
    some PINs shorter than others.

    Re-drawn if it lands on a trivial value. That biases the distribution by
    the few hundred values removed — immaterial against a million, and better
    than issuing a child `123456` because chance produced it.

    Nothing about the child is mixed in: not the admission number, the date of
    birth, the phone number, the name or the year. That is invariant A5, and a
    PIN derived from any of them is a PIN their classmates can guess.
    """
    for _ in range(64):
        candidate = f"{secrets.randbelow(10 ** length):0{length}d}"
        if not is_trivial(candidate):
            return candidate

    # Unreachable in practice — the trivial set is a rounding error against
    # 10**6. Raising beats returning a weak PIN or looping for ever.
    raise WeakPin("Could not generate a PIN that meets the policy.")


def describe_policy() -> dict:
    """What a client may tell somebody about the rules, without listing them.

    The trivial set is deliberately not published: an attacker who knows which
    PINs are refused knows which to skip, and the list is small enough for
    that to matter.
    """
    return {
        "length": PIN_LENGTH,
        "digits_only": True,
        "leading_zeros_allowed": True,
        "rejects_trivial_patterns": True,
    }
