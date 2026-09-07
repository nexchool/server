# Integrations

Calling other people's services, without the rest of the codebase knowing who.

> Not to be confused with **platform billing** (`modules/billing`), which holds
> the same vendors' commercial records. That module knows what a message
> costs; this one knows how to send it. See *The two provider tables* below —
> the distinction is the one most likely to be got wrong.

---

# Purpose

A feature asks for a **capability** — "send an SMS" — and this module decides
which vendor carries it for that school, calls it with a timeout, normalizes
whatever comes back, and records that it happened so billing can price it.

The rule the whole module exists to enforce:

    Business modules request a capability.
    They do not know which external provider implements it.

So a feature that wants to send a message says

```python
send_sms(tenant_id=..., destination=..., body=..., purpose="fee_reminder")
```

— or `send_whatsapp`, or `messaging.send_message(channel=...)` directly, the
way `modules/auth/otp.py` does once it has read the school's chosen
channel — and never

```python
some_vendor_client.messages.create(...)
```

inside an authentication strategy. Provider selection is this layer's job, and
a strategy that knew a vendor would mean changing vendor requires editing the
login path.

---

# Concepts

## Capability

What a feature wants done. `sms` and `whatsapp` today, grouped under
`MESSAGING_CAPABILITIES` because both deliver a message to a person and a
school's OTP channel choice ranges over exactly that pair — a future
capability that is not a message (a payment, a lookup) must not silently
become an option on that menu. A capability earns its place by having a
caller, not by being imaginable.

WhatsApp is not a second authentication method. The method stays
`mobile_otp`; WhatsApp is one of the wires its code can go down, chosen by
`tenant_auth_policies.otp_delivery_channel` and never both at once — see
ADR-021.

## Provider client

How NexSchool actually calls one external service. Declares its metadata as
class attributes — `key`, `capability`, `supports_idempotency`, `is_billable`,
`is_test_double` — so the registry can check its shape without instantiating
it, the same way authentication strategies do.

Two of those are load-bearing rather than descriptive. `supports_idempotency`
decides whether a timed-out send may be retried. `is_billable` decides whether
a success reaches the usage ledger.

## Tenant integration

Which provider carries one capability for one school, with what settings and
whether it is switched on. Tenant-scoped, because two schools may use
different vendors for the same thing.

## Registry

Every provider client this build can execute — a dict populated at import, not
a plugin loader, so "which providers does this build have" is answerable by
reading a file. `validate()` runs at import and refuses to start on an
incoherent registry.

**Registering a provider is what makes it possible. A school's integration row
is what makes it used.**

## Message template

A message is a **purpose plus variables**, resolved against a template the
school registered (`templates.py`) — neither channel this build supports
sends free text. `MessageTemplate(id, variables)`: a vendor template id, and
the ordered names of the slots it exposes.

The two vendors want those slots filled two different ways. MSG91's Flow API
has no field for message text at all — the wording lives in a flow already
registered under India's DLT regime, and a send fills that flow's own
**named** variables (`##OTP##`, `##MINUTES##`), so SMS gets a **dict**.
Meta's WhatsApp templates take their variables **positionally** — an ordered
list, no names anywhere — so WhatsApp gets a **list**. `send_message` zips a
caller's positional values against the school's registered variable names for
SMS, and refuses a count mismatch before any provider is called, rather than
silently truncating to the shorter side.

A **bare string** template (`"1707169900000000000"`, no `variables`) still
resolves — that is every row registered before this concept existed, and it
is correct for WhatsApp, which ignores names entirely, while a channel that
needs named slots (SMS) is refused at the send layer if it is used with one.

Which template serves a purpose is per-school, per-channel configuration on
the integration row (an identifier, not a secret) — two schools sharing one
vendor account may have registered different wordings.

---

# The two provider tables

They look similar and are not.

| | `service_providers` / `tenant_services` (Phase 2) | `tenant_integrations` (Phase 3) |
|---|---|---|
| Answers | what does this school buy, at what price | whose wire does this school's work go down |
| Lifetime | outlives a routing change | changes when the vendor changes |
| Holds | rates, terms, estimates | endpoint settings, credential *references*, status |
| Never holds | an endpoint, a key, a retry policy | a price |

They share one thing: a vendor identity. `tenant_integrations.provider_key`
matches `service_providers.key`, so an operator reading a bill and an operator
reading a log see the same name.

A school can be commercially signed up to two SMS vendors while only one
carries live traffic. That is why routing is not a column on a billing row.

**A service key is unique per provider, not globally.** Two vendors can both
sell something keyed `sms`, so any lookup by service key alone has two answers
once a school has two suppliers. `record_usage` and `configure_tenant_service`
both take an optional `provider_key` and **refuse an ambiguous lookup rather
than resolving it by picking the first row** — a charge against an arbitrary
supplier is worse than one that fails loudly.

---

# Configuration and secrets

The repository stores every credential it has as an environment variable, and
has no encryption at rest, no key management and no secret store. Phase 3 does
not invent one, and specifically does not invent the convenient thing: a
plaintext credential column.

**Configuration metadata** — a sender id, a route, a base URL — is stored on
the tenant's integration, returned by APIs and safe in a log.

**Secret material** — an API key, a token — is never stored. The database
holds the *name of the environment variable* the value lives in. Reading a
`tenant_integrations` row tells you which credential is in use and nothing
about what it is.

That reference costs almost nothing and buys the property that matters: a
database dump contains no provider secrets, and an API response that forgot to
redact one has nothing to reveal. A value pasted into a reference field is
refused, which is the point of the field.

When a school one day brings its own vendor account and the secret genuinely
has to be per-tenant, this is the seam to change — and that change is envelope
encryption with a managed key. Deliberately not done here: it would be the
first secret in this repository to live in the database at all, and it is not
needed to select a provider.

---

# Provider resolution

One resolver, `resolve_provider(tenant_id=..., capability=...)`. Provider
selection duplicated across modules is how two answers to one question come to
exist, and this is a question where two answers means a school's messages
going down a wire nobody expected.

    capability known?          no  → UnknownCapability
    school named?              no  → refused; a tenant-less resolution would
                                     pick somebody's provider
    integration row, enabled?  no  → NoIntegrationConfigured
    provider registered?       no  → refused, never a silent fallback
    test double outside tests? yes → refused

There is no configuration hierarchy. A school's integration row is the only
source, deliberately: inventing a precedence — tenant, then platform default,
then environment — before anything needs one would mean a school's provider
could change because of a setting nobody looked at.

**Never put provider selection in `tenants.feature_flags`.** That column
merges and never prunes, so keys outlive their modules; a stale stored value
has already switched a module on in production once.

---

# Normalized errors

A caller decides what to do without parsing a vendor's exception strings.

| Code | Retryable | Meaning |
|---|---|---|
| `configuration_error` | no | something is missing in the setup |
| `authentication_error` | no | the provider rejected our credentials |
| `validation_error` | no | the request was wrong; the same one will fail again |
| `rate_limited` | **yes** | going too fast |
| `timeout` | **no** | see below |
| `provider_unavailable` | **yes** | down or unreachable |
| `provider_rejected` | no | understood and declined |
| `unknown_provider_error` | no | unclassified |

**`timeout` is deliberately not retryable.** A timeout means we do not know
what happened: the provider may well have accepted the request and sent the
message, and a retry would send a second one and charge the school twice.

    request sent → provider processed it → network timed out
                 → client retries → a second SMS, a second charge

A provider that honours an idempotency key makes that retry safe, so the
decision belongs with the provider that knows whether it does
(`supports_idempotency`). This layer will not guess on a billable operation.

---

# Idempotency and usage

    provider call succeeds
            ↓
    normalized result
            ↓
    usage recorder
            ↓
    ServiceUsageRecord   (Phase 2)

The provider's own message id becomes Phase 2's `external_reference`, so
idempotency is the provider's identity rather than a second deduplication
scheme invented here — a replayed delivery callback naming the same message
cannot bill it twice.

Where a provider returns no id, the operation id is used instead. That is a
deliberate and weaker fallback: it is unique per call rather than per message,
so it makes *that write* idempotent without making a provider's repeated
report of one send idempotent. **A provider that returns no reference cannot
have exactly-once billing**, and saying so is better than implying otherwise.

Failing to record usage is not treated as failing to send. The message has
already gone; raising would tell the caller it failed and invite a retry that
sends another. An unbilled message is a smaller problem than a duplicated one.

## What "success" means

A provider accepting an API request is not a handset receiving a message.

| Status | Meaning |
|---|---|
| `accepted` | the provider took the request — all most providers tell you |
| `sent` | the provider handed it to a carrier |
| `delivered` | it reached the handset — **only ever from a delivery receipt** |
| `failed` | it did not work |

Nothing in this codebase may upgrade `accepted` to `delivered` without a
receipt to stand on.

---

# The billing boundary

    integration  →  usage  →  billing

never

    integration  →  billing calculation

and never

    billing  →  provider API

The integration layer records **what happened**. Billing works out what that
costs, later, from stored terms — so a total stays deterministic and does not
depend on a vendor being up. Both directions are asserted by tests that parse
imports, on the principle that a boundary holding only because nobody has
crossed it yet is not a boundary.

---

# Health checks

The temptation with a "test connection" button is to prove it works by doing
the thing. For SMS that charges the school for every press and rings a real
person's phone, so a health check **sends nothing**.

What it answers honestly: is there a row, is it enabled, does this build have
a client for that vendor, are the named credentials actually set, and — only
where a vendor offers a free non-sending check — is it reachable. When the
last one is unavailable the report says delivery was not verified rather than
implying it was.

Enabling an integration whose credentials are absent is refused: an
integration switched on that cannot work produces a school whose messages fail
silently.

**Disabling is refused too, while a paid sign-in method still depends on it.**
`set_integration_status` (`services.py`) checks `methods_depending_on`, which
is derived rather than listed: a strategy is a dependant when it declares
itself `is_paid` and the school's `otp_delivery_channel` names this
capability. Turning the integration off first would leave a sign-in method on
the login screen whose codes silently never arrive; the operator is told to
turn the method off first instead. A channel a school has not chosen to
receive OTP on is not a dependency — disabling it breaks nothing.

## Verifying delivery — the test-send route

`POST /platform/tenants/<id>/integrations/<capability>/test-send` sends one
real, billable message and is deliberately **not** folded into the health
check above — a "test connection" button that quietly sends a message is the
trap this section already argues against. It goes through the same template
path as a real send (`purpose="integration_test"`), so it also proves the
thing that most often fails: a template that was never registered. Recorded
in the usage ledger with `usage_type="integration_test"`, same as any other
send, so it appears on the school's bill like the real messages it stands in
for. Rate-limited to 5 per hour per acting operator (not per address — a
school behind one NAT should not share a limit, and an attacker with a proxy
pool should not evade one).

## The outbox — reading what a test double pretended to send

A fake provider that returns success and throws the message away makes
`mobile_otp` (and a WhatsApp test-send) unverifiable end to end: the code
exists and is valid for five minutes, and nothing anywhere says what it is.
`outbox.py` is the smallest fix — an in-memory, bounded ring buffer (50
messages) that `messaging.send_message` writes to only after a **test
double** (`is_test_double`) reports success. A real provider never reaches
it: a real OTP's body is a live secret, and keeping this in memory only works
because it only ever holds fictional ones.

`GET /platform/integrations/outbox` reads it back, newest first. It 404s
(not 403 — an endpoint that exists and refuses tells an attacker it exists)
wherever `resolver._test_doubles_allowed()` says a fake may not run — the
same predicate the resolver itself uses, so "may a fake run here" has one
answer rather than two that could disagree.

---

# Logging

Enough to debug a failure, and nothing that should not be in a log file.

Logged: tenant id, provider key, capability, operation id, normalized error
code, latency.

**Never logged:** the message body — for OTP that *is* the secret — any
credential, or a full phone number. A destination is reduced to its last two
digits plus a short digest, which is enough for somebody holding a support
ticket to confirm they are on the right line.

The repository documents an `X-Request-Id` convention it does not implement:
nothing generates a request id and there is no logging configuration at all.
Building that is an observability project and this is not it, so each
integration call mints its own operation id, which reaches the logs and the
usage record. If a real correlation id arrives later, that is one function to
change.

---

# No vendor can be enabled

Two real providers are registered — `msg91` (SMS) and `meta_whatsapp`
(WhatsApp) — alongside the `fake_sms` / `fake_whatsapp` test doubles the
resolver refuses to hand out outside testing or debug. Registering a client
is not the same as being able to use it: both real providers declare
`required_credentials`, `capability_health` reports either one not-ready
until its credential is actually set on this server (`MSG91_AUTH_KEY`,
`META_WHATSAPP_ACCESS_TOKEN`), and `set_integration_status` refuses to enable
either one before that — an operator who configures a school onto either
vendor today gets a clean refusal, the same as if it were unregistered.

Standing up the commercial account behind either client — MSG91's DLT entity
registration, or Meta's business verification and an approved authentication
template — is a decision nobody has finished taking. Phase 2 shipped the
billing catalog empty for the same reason: nothing seeds it, so a school is
signed up to a vendor commercially only when an operator does it on purpose.
See `../operations/otp-vendor-registration.md` for what remains before
either one can actually send.

---

# How OTP connects to this

**Built**, since Phase 4, and Phase 9 changed one line of it — the channel is
no longer fixed:

```
Mobile OTP strategy
        ↓
OTP service                                    ← generates and verifies the code
        ↓
messaging.send_message(channel = otp_delivery_channel(tenant))   ← this module's surface
        ↓
resolve_provider(tenant, channel)
        ↓
template_for(configuration, purpose)           ← Phase 9: no channel sends free text
        ↓
the school's provider client
        ↓
normalized MessageSendResult
        ↓
ServiceUsageRecord                             ← Phase 2's ledger
        ↓
a billing component on the school's estimate
```

`modules/auth/otp.py::_deliver` calls `messaging.send_message` directly
rather than through the `send_sms` / `send_whatsapp` named surfaces, because
it does not know which of the two it wants until it reads the school's
`otp_delivery_channel` — see `../modules/mobile-otp-authentication.md`'s
*Channel choice* section and `../architecture/adr/ADR-021-one-otp-channel-no-fallback.md`.
No HTTP call, no vendor name, no retry policy and no price appears in the
authentication module — asserted by a test that parses every import under
`modules/auth/` — and `purpose` remains the only thing OTP passes down.
