# ADR-021 — One OTP Channel, No Automatic Fallback

## Status

Accepted

---

## Date

2026-09-07

---

# Context

`mobile_otp` sends its code down whichever channel `tenant_auth_policies.
otp_delivery_channel` names for that school — `sms` by default, `whatsapp` if
the school switched (migration 134). Until Phase 9, `sms` was the only
messaging capability that existed, so there was nothing to choose between.

Phase 9 added a second one. `modules/integrations/capabilities.py` now groups
`sms` and `whatsapp` under `MESSAGING_CAPABILITIES`, `messaging.py` carries
both down one send path, and a school picks the one it wants with
`set_otp_delivery_channel`. The moment a second channel exists, the obvious
next thought is: why not both? If SMS fails, try WhatsApp. Belt and braces.

That thought is worth writing down and refusing on purpose, because nothing in
the code stops someone from reaching for it later — `resolve_provider` and
`_deliver` (`modules/auth/otp.py`) both already take a single `channel`
argument, and threading a second one through would look like a small change.

---

# Decision

**A school's sign-in codes go down exactly one channel. There is no automatic
fallback from SMS to WhatsApp or back.**

`otp_delivery_channel` is one column holding one value, constrained to
`'sms'` or `'whatsapp'` (migration 134's check constraint). Changing it is a
deliberate, audited operator action (`set_otp_delivery_channel` — "choose the
wire, not the method"), not something the delivery path decides for itself in
the moment a send fails.

If the chosen channel's provider is unhealthy, `_deliver` marks the challenge
`failed` and returns. It does not retry on the other channel. It does not
retry at all — `messaging.send_message` already treats a timeout as
not-retryable for the same reason: a request that may have already been
accepted must not be repeated.

---

# Rationale

## A channel a school did not choose is not free to use

A school picks WhatsApp because that is the wire it pays for and the wire its
families expect a message on. Falling back to SMS the moment WhatsApp is slow
would mean charging that school for a channel it never selected, on terms it
never agreed to, and putting a message on a wire its families were not told to
expect one on. `messaging.send_message` records usage under whichever
capability actually sent — a silent fallback would make that record say
something the school did not do.

## Two channels double the failure surface for one feature

`otp_delivery_channel` exists precisely so failure has one cause to
investigate: the school's chosen provider, and nothing else. A fallback chain
means an OTP failure could now originate in either provider, or in the logic
that decides when to hop between them — a third thing to get wrong, on the
one authentication method that already has no stored secret to fall back to
if delivery fails outright.

## A bill that fell back is a bill nobody can explain

`usage_recorder.record_provider_usage` writes one row per accepted send,
keyed to the capability that actually carried it. A fallback would sometimes
produce a WhatsApp row and sometimes an SMS row for what the school still
thinks of as one setting — "how our parents get sign-in codes" — and
explaining a month's bill back to an operator would mean reconstructing,
message by message, which channel happened to be up. `ADR-021`'s bet is that
an outright outage is easier to explain than a bill that quietly changed
shape underneath a setting nobody touched.

---

# Consequences

## What this makes easy

- One provider's health decides whether `mobile_otp` works for a school —
  `messaging_health` already answers that question for exactly the channel in
  `otp_delivery_channel`, and `set_tenant_auth_method` refuses to enable the
  method until it does.
- A bill is explained by one channel's rate and one channel's volume, never a
  mix decided by machinery an operator cannot see.
- Switching channels stays a `set_otp_delivery_channel` call — no fallback
  ordering, no "primary/secondary" configuration to design or seed.

## What this costs

**A channel outage is an outage.** If a school's WhatsApp provider is down and
nothing routes around it, that school's OTP sign-in stops working until the
provider recovers or an operator switches the channel by hand. There is no
built-in resilience against a single vendor's downtime, and there is no
resilience feature to point to when a school asks for one.

## Trigger to reopen

This should be revisited if measured delivery failure on one channel — not a
single outage, but a pattern — makes the cost above outweigh the reasons
against it. That would want, at minimum: per-channel failure-rate data over
time (the usage ledger and `MessageSendResult.error_code` already carry the
raw material), a decision on who bears the cost of a fallback message sent on
a channel the school did not choose, and a decision on how that message is
disclosed on the bill rather than folded silently into the chosen channel's
line.

---

# Alternatives considered

**Automatic fallback, same message, other channel** — rejected. Doubles the
failure surface for the reason above, and bills a school for a channel it did
not select.

**Automatic fallback, operator opt-in per school** — rejected for now, not
forever. This is the shape a reopened decision would likely take, but it is a
second configuration axis (ordering, timeout-before-fallback, cost
attribution) on top of a feature that has shipped for exactly one send
attempt so far. Building it ahead of a measured need would be guessing at
requirements no school has stated.

**Retry the same channel before giving up** — out of scope for this ADR.
`messaging.send_message` already refuses retries on a billable, non-idempotent
send unless the provider proves it supports an idempotency key
(`supports_idempotency`) — neither `msg91` nor `meta_whatsapp` does. That is
an existing, narrower rule about retrying the *same* request, not about
routing to a *different* channel, and this ADR does not change it.

---

# Related

- `modules/integrations/capabilities.py` — `MESSAGING_CAPABILITIES`
- `modules/auth/policy.py` — `otp_delivery_channel`, `set_otp_delivery_channel`
- `modules/integrations/messaging.py` — `send_message`, the one send path
- `modules/integrations/usage_recorder.py` — per-capability usage recording
- `migrations/versions/134_which_wire_a_schools_codes_go_down.py`
- `../../modules/mobile-otp-authentication.md`
- `../../modules/integrations.md`
