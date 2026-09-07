# OTP Vendor Registration Checklist

What has to be true outside this codebase before a school can receive a real
SMS or WhatsApp sign-in code. Nothing here is code — the machinery
(`modules/integrations/`, `msg91.py`, `meta_whatsapp.py`) is built and
registers cleanly; both real providers are unusable today because none of the
paperwork below has been started. **This is the critical path**, not a
follow-up task: no amount of further code substitutes for a DLT entity, a
WhatsApp Business Account, or an approved template, and `set_integration_status`
already refuses to enable either provider until its credential is present, and
`set_tenant_auth_method` refuses to enable `mobile_otp` itself until the
school's chosen channel passes its health check (see below). The paperwork
gates the feature; the code does not.

---

# SMS — MSG91

MSG91 (`modules/integrations/providers/msg91.py`) talks to MSG91's Flow API,
which requires every one of the following to exist before a send can
succeed.

## 1. DLT entity registration

India's Telecom Regulatory Authority requires the sender of a commercial SMS
to be registered as an entity with a telecom operator's DLT platform (e.g.
Airtel's, Jio's, Vodafone Idea's — MSG91 can register through the one it
partners with). This is an organisational registration, not a per-message
one, and it needs:

- **GST registration or CIN** (Corporate Identification Number) — proof the
  registering entity is a real, registered business.
- **PAN** (Permanent Account Number) of the entity.
- **An authorised signatory** — a named person empowered to sign for the
  entity, whose details go on the registration.

This step alone routinely takes days and cannot be shortened by anything in
this codebase.

## 2. A six-character transactional sender header

Once the entity is registered, it registers a **sender id** — exactly six
characters, alphabetic, e.g. `NXSCHL` — the header recipients see in place of
a phone number. This becomes `sender_id` on the school's `tenant_integrations`
configuration (`msg91.py` reads `configuration.get("sender_id")`); it is an
identifier, not a secret, and belongs there rather than in an environment
variable.

## 3. A content template matching `build_otp_message` exactly

A DLT-registered **content template** must be registered with the wording the
OTP actually sends, with the code as a declared variable. The wording to
register is whatever `modules/auth/otp_message.py::build_otp_message`
currently produces:

```
{code} is your NexSchool sign-in code. It expires in {minutes} minutes. Do not share it with anyone.
```

The operator registering the template must copy this text (or generate it by
calling `build_otp_message` with a placeholder) rather than retype it from
memory — DLT match-checking is exact, and a template that does not match word
for word is rejected by the operator at send time, not by MSG91's API in a way
this codebase can catch in advance. If `otp_message.py` is ever edited, the
registered template has to be re-registered to match — the module docstring
already says this is why the wording lives in its own file.

## 4. Link the MSG91 account to the DLT entity, and record the flow

With the entity and template both live, MSG91's dashboard is used to create a
**Flow** against the registered template, which is where MSG91's Flow API
gets its `flow_id` and its declared variable *names* — this is the step that
is easy to get backwards. MSG91's Flow API has no field for message text at
all (see `msg91.py`'s module docstring); it only accepts a `flow_id` and a
mapping of that flow's own named variables to values. **The flow's variable
names, exactly as MSG91's dashboard shows them, must be recorded in the
school's integration configuration** as `templates.py`'s
`{"id": <flow_id>, "variables": [<names in order>]}` — `messaging.send_message`
zips `modules/auth/otp_message.py::otp_variables()`'s positional `[code,
minutes]` against those names before ever calling MSG91, and a mismatched or
missing variable name produces a `CONFIGURATION_ERROR` refusal rather than a
message with the wrong values in it.

## Environment variable

| Variable | What it holds | Secret? |
|---|---|---|
| `MSG91_AUTH_KEY` | The MSG91 account's auth key | **Yes** — server env var only |

## On the school's integration row, not in the environment

| Field | Example |
|---|---|
| `sender_id` | `NXSCHL` |
| `templates.authentication_otp.id` | the MSG91 `flow_id` |
| `templates.authentication_otp.variables` | `["OTP", "MINUTES"]` — the flow's own variable names, in the order `otp_variables()` supplies them |

---

# WhatsApp — Meta Cloud API

Meta's WhatsApp Cloud API (`modules/integrations/providers/meta_whatsapp.py`)
requires a separate, unrelated set of registrations.

## 1. Meta Business account and business verification

A **Meta Business Account** (business.facebook.com) is the prerequisite for
everything else. Sending authentication messages at any real volume requires
**business verification** — Meta reviewing the business's identity — which
has its own document requirements and its own review turnaround, outside this
codebase's control.

## 2. A WhatsApp Business Account and a phone number

A **WhatsApp Business Account (WABA)** under that Meta Business Account, with
a **phone number that has never been on the consumer WhatsApp app**. A number
already active on regular WhatsApp (or WhatsApp Business) cannot simply be
promoted to the Cloud API — it has to be a number with no existing WhatsApp
registration, or one explicitly migrated off the consumer app first. Getting
this wrong late (discovering the intended number is already in personal use)
is the kind of delay worth ruling out early.

## 3. An authentication-category template — and the mandatory button

Meta requires every message to go through a pre-approved **template**, and an
OTP send specifically needs a template in the **Authentication** category, not
Utility or Marketing.

> **This is the step most likely to be underestimated.** Per
> `meta_whatsapp.py`'s own module docstring (citing Meta's authentication
> template documentation, read 2026-09-07): an authentication-category
> template is not just a body with a `{{1}}` placeholder for the code. It
> requires a **mandatory button component** — one-tap autofill or a
> copy-code button — that a plain utility template does not carry. **This
> client does not construct that button component.** `templates.py`, this
> codebase's only record of a school's registered template, carries an id and
> an ordered tuple of variable *names* — it has no concept of a template's
> button shape at all.
>
> A body-only send against a real authentication template will fail with a
> clear `VALIDATION_ERROR` (Meta rejects the request; `meta_whatsapp.py`
> normalizes that rejection the same way it normalizes any other malformed
> request) — not a silent failure, but a failure all the same, and one that
> cannot be closed by writing code speculatively. **Closing this needs a real
> approved template to validate the button's shape against** — building the
> button-construction code before a template exists to test it on would mean
> guessing at Meta's payload shape a second time (the first guess is already
> recorded and cited in the module docstring) with no way to confirm it is
> right. Register the template first; add button support once there is
> something real to send it against.

## 4. A permanent system-user access token — not the quickstart token

`META_WHATSAPP_ACCESS_TOKEN` must be a **permanent token generated for a
System User** on the Meta Business account. The Cloud API's own quickstart
issues a **24-hour token** for testing, and that token expiring mid-production
is an outage with no code fix — it is an unscheduled credential rotation.
`resolve_secret` cannot tell the two kinds of token apart; getting this right
is entirely on whoever provisions the variable.

## Environment variable

| Variable | What it holds | Secret? |
|---|---|---|
| `META_WHATSAPP_ACCESS_TOKEN` | The permanent system-user access token | **Yes** — server env var only |

## On the school's integration row, not in the environment

| Field | Example |
|---|---|
| `phone_number_id` | Meta's phone number id — the URL path segment `meta_whatsapp.py` sends to; the one field this client actually reads |
| *(WABA id)* | worth recording on the same row for reference — `meta_whatsapp.py`'s docstring says the business account id belongs on `configuration` alongside `phone_number_id`, but does not fix a key name, since nothing in this client reads it yet |
| `templates.authentication_otp.id` | the approved template's name |
| `templates.authentication_otp.variables` | the template body's variable names, in the order `otp_variables()` supplies them (positional for WhatsApp, so names here are for the school's own record — Meta does not use them) |
| `language` | e.g. `en` — defaults to `en` if omitted |

---

# Neither provider works without both halves

A credential with no template registered fails at `templates.template_for`
before any network call (`TEMPLATE_NOT_CONFIGURED`). A template with no
credential set fails at the provider's own `send` (`CONFIGURATION_ERROR`).
Both halves — the vendor-side registration above, and the corresponding
`tenant_integrations` row with its credential reference and template
configuration — are required before `capability_health` reports the
integration ready.

---

# A working integration still will not bill — the billing catalog is a separate step

Getting a provider to `ready` (the section above) makes it able to **send**.
It says nothing about whether sending is **billed**, and nothing in this
build's health check, `set_integration_status`, or `set_tenant_auth_method`
checks the billing half at all.

`record_usage` (`modules/billing/usage.py`) looks up the school's
`TenantService` for the capability being sent on, and raises `UnknownService`
if none exists. `usage_recorder.record_provider_usage` catches exactly that
exception, logs it once at `ERROR`, and returns — deliberately: a failure to
record billing must not turn an already-sent message into a reported
failure, or a caller would retry it and the school would be charged twice
for one message. That is the right call for the send path, and it has a
real cost here: **an unbilled message looks identical to a billed one to
everybody except whoever is watching the error log.**

Neither `sms` nor `whatsapp` has a billing catalog entry on a fresh
deployment. Nothing seeds one — no migration, no seeder, no onboarding step
creates a `ProviderService` or a `TenantService` for either capability — so
this is not a WhatsApp-specific gap: it is true of SMS as well, on every
environment where an operator has not done the two steps below by hand. See
debt 61 in `../architecture/debt-register.md`.

**Before the first billable message on either channel, for every school
using it:**

1. `POST /platform/service-catalog/services` (`upsert_provider_service`) —
   register the capability (`sms` or `whatsapp`) as something the provider
   sells, with a rate. Once per provider, not once per school.
2. `POST /platform/tenants/<id>/services` (`configure_tenant_service`) —
   subscribe that specific school to it.

Skipping either step is invisible at every point that would normally catch a
misconfiguration: the integration enables cleanly, the health check reports
ready, `test-send` succeeds, and real OTPs or WhatsApp messages go out and
arrive. The only trace is the `ERROR` log line `record_provider_usage`
writes on every send — nothing pages on it, and nothing on any screen tells
an operator the catalog is missing. Confirm the subscription exists (`GET
/platform/tenants/<id>/services`) as part of standing up either channel, not
only when a bill looks short.

---

# The paperwork gates the feature, not the code

`set_tenant_auth_method` (`modules/platform/routes.py`) refuses to enable
`mobile_otp` for a school unless `messaging_health(tenant_id,
otp_delivery_channel(tenant_id))` reports `ready`. That check asks, in order:
is there an integration row, is it enabled, does this build have a client for
the vendor, and — the step every item above exists to satisfy — are the named
credentials actually set on this server. Until an operator has been through
the checklist above for whichever channel a school picks, that health check
fails, correctly, and `mobile_otp` cannot be switched on for that school —
regardless of how complete the code is.

Use `POST /platform/tenants/<id>/integrations/<capability>/test-send` (see
`../modules/integrations.md`) to prove a configuration actually works, once
health reports ready — it sends one real, billable message, so run it
deliberately, not as a matter of routine.
