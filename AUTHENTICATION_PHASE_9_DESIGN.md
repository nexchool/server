# Authentication — Phase 9: Operations & Messaging Integration

**Status: design approved, not yet implemented.**
**Written 2026-09-07, on `develop`, on top of Phase 8 (`fdb12c8`).**

Phase 8 made the authentication policy authoritative — the pipeline reads it,
and a method switched off ends the sessions opened with it. What Phase 8 did
not do is give anybody a way to *switch one on*. The policy is written by
`PATCH /platform/tenants/<id>/auth-policy/methods`, and the only screen that
shows it says, in words, that it is read-only.

That is the whole of Phase 9: the operational layer that makes a designed
system an operable one, and the messaging providers without which one of the
methods cannot work at all.

---

## 1. What already exists

This is the section to read before writing anything, because most of the
backend for this phase was built in Phases 2–4 and is easy to build twice.

| Concern | Where | State |
|---|---|---|
| Read a school's policy | `GET /platform/tenants/<id>/auth-policy` | Done |
| Write the two non-method settings | `PATCH …/auth-policy` | Done |
| Turn one method on or off | `PATCH …/auth-policy/methods` | Done |
| Refuse to enable a method that cannot work | `routes.py::set_tenant_auth_method` | Done, SMS only |
| End sessions opened with a disabled method | `policy.end_sessions_opened_with` | Done |
| What capabilities this build has | `GET /platform/integration-capabilities` | Done |
| A school's providers, with health | `GET`/`POST /platform/tenants/<id>/integrations` | Done |
| Enable / disable an integration | `PATCH …/integrations/<capability>/status` | Done |
| Provider abstraction | `modules/integrations/` — registry, resolver, base, results | Done |
| Usage → billing | `usage_recorder` → `ServiceUsageRecord` → annual statement | Done |
| A test double | `providers/fake.py`, refused outside TESTING/DEBUG | Done |

**Nothing in that table is to be redesigned.** Phase 9 extends it.

What is genuinely missing is four things: a second channel, a template
concept, a way to read what a fake sent, and every screen.

---

## 2. Decisions taken before this spec was written

Recorded because each one closes off an option somebody will otherwise reopen.

**Provider accounts belong to NexSchool, not to schools.** One vendor account
per capability, resold to tenants. Credentials therefore stay exactly as
`credentials.py` has them — environment variable *names* in the database,
values only in the process environment. No encryption at rest, no key
management, no secret ever in a row. Schools bringing their own vendor account
is a real future requirement and is the seam `credentials.py` already names;
it is not this phase.

**MSG91 for SMS, Meta WhatsApp Cloud API for WhatsApp.** MSG91 because it is
domestic, cheapest of the options considered, and treats DLT template IDs as a
first-class parameter rather than an afterthought. Meta directly rather than
through a BSP because API access is free and there is no reseller margin on
each conversation. Two vendors costs nothing architecturally — `sms` and
`whatsapp` resolve independently through the same resolver.

**No vendor paperwork is started.** No DLT entity registration, no approved
sender header, no approved template, no Meta Business account. Both real
adapters are therefore written to the full registered-template contract — the
only shape that will ever work in production — and neither can be enabled
until its environment variables exist, which `capability_health` already
enforces. Live testing happens through the fakes until credentials arrive.

**One OTP, one channel, no fallback.** Automatic SMS↔WhatsApp failover is
deliberately not built. It doubles the failure modes and the billing
explanation for a reliability problem nobody has measured yet.

---

## 3. Templates: the requirement that changes the message layer

Both chosen channels refuse free text.

Under India's DLT regime an SMS is delivered only when its body matches a
template registered against the sender's entity, and the send carries that
template's ID. Meta will not send an authentication-category WhatsApp message
except through a template approved in advance, and the send carries the
template *name* plus its variables positionally — not a body at all.

`otp_message.build_otp_message` returns a formatted string. That is correct
for a fake and undeliverable through either real vendor. This is the strongest
argument for having written a real adapter this phase rather than only fakes:
a boundary designed with nothing but a test double behind it would have
shipped a `message: str` parameter and been wrong.

### The shape

A message becomes a **purpose plus variables**, and the template that carries
it is per-school, per-channel configuration:

```
purpose:   "login_otp"
variables: {"code": "418302", "minutes": "5"}
```

resolved against the integration's non-secret `configuration`:

```json
{
  "sender_id": "NEXSCH",
  "templates": { "login_otp": "1707169900000000000" }
}
```

`build_otp_message` stays, and gains a sibling that returns the variables. The
rendered text remains the canonical record of *what was registered* — it is
what gets submitted to DLT and to Meta for approval, and it is what the fake
provider renders into the outbox so a developer sees the real wording.

A send whose purpose has no configured template is refused **before** the
provider is called, with `template_not_configured`. Discovering a missing
template from a vendor's rejection code is a worse day than discovering it
from our own.

---

## 4. Capability layer: from SMS to messaging

```
capabilities.py     CAPABILITY_WHATSAPP alongside CAPABILITY_SMS
                    MESSAGING_CAPABILITIES = (sms, whatsapp)

base.py             MessagingProvider  (shared: health, idempotency, billing)
                      ├── SmsProvider       send(destination, body, template_id, …)
                      └── WhatsAppProvider  send(destination, template_name, variables, …)

results.py          SmsSendResult → MessageSendResult   (straight rename)

messaging.py        send_message(tenant_id, channel, purpose, destination,
                                 variables, idempotency_key)
                    ← the single entry point: resolve, call, normalize, record
sms.py              send_sms()      thin named surface over send_message
whatsapp.py         send_whatsapp() thin named surface over send_message
```

The two `send` signatures differ on purpose. Collapsing them into one
`message: str` would hide the fact that WhatsApp never receives a body, and
the hiding is where the bug would live.

Everything that is currently right about `sms.py` — one resolution point, one
redaction point, one usage-recording point, results rather than exceptions,
no body and no number in any log line — moves into `messaging.py` unchanged.
The rename is mechanical; all of it is one commit old and has no external
consumers.

---

## 5. OTP picks a channel

New column on `tenant_auth_policies`:

```
otp_delivery_channel   'sms' | 'whatsapp'   NOT NULL DEFAULT 'sms'
```

Migration **134**, chaining off 133.

- `policy.otp_delivery_channel(tenant_id)` reads it; `policy.set_otp_delivery_channel`
  writes it; `policy.describe` returns it.
- `otp._deliver` calls `send_message(channel=…)` instead of `send_sms`.
- `routes._method_needs_sms` becomes `_method_needs_messaging` and checks the
  health of the school's **chosen** channel. A school on WhatsApp must not be
  blocked by an SMS gap it does not use — the current code would block it.
- Changing the channel while `mobile_otp` is enabled is refused unless the new
  channel is healthy, for the same reason enabling the method is.

---

## 6. Providers

| Key | Class | File | Notes |
|---|---|---|---|
| `fake_sms` | `FakeSmsProvider` | `providers/fake.py` | Exists; gains outbox recording |
| `fake_whatsapp` | `FakeWhatsAppProvider` | `providers/fake.py` | New, same behaviour knobs |
| `msg91` | `Msg91Provider` | `providers/msg91.py` | New |
| `meta_whatsapp` | `MetaWhatsAppProvider` | `providers/meta_whatsapp.py` | New |

Both real adapters:

- declare `required_credentials`, so `capability_health` reports them missing
  and `set_integration_status` refuses to enable — no new mechanism needed;
- declare `supports_idempotency` **honestly**. If a vendor does not honour an
  idempotency key, it says so and `messaging.py` will not retry it after a
  timeout, because the first request may have been delivered and the school
  would pay twice;
- implement `health()` **without sending**, using the vendor's free balance or
  metadata endpoint where one exists, and otherwise reporting configuration
  readiness and saying plainly that delivery was not verified;
- normalize every vendor error into `errors.py`'s existing codes. No vendor
  shape escapes the module.

Exact endpoints, parameter names and error codes are to be read from each
vendor's current documentation at implementation time and not from memory.
The adapters are covered by tests against a mocked HTTP layer (`http.py`), so
a documentation error surfaces as a failing test rather than as a school's
messages silently not sending.

---

## 7. Reading what a fake sent

The gap that blocks testing `mobile_otp` today: `FakeSmsProvider.send`
returns a reference and throws the body away, so even in development, where
the resolver permits a test double, there is no way to learn the code.

**`modules/integrations/outbox.py`** — a bounded in-memory ring buffer
(capacity ~50). The fake providers append `(tenant_id, channel, destination,
rendered_body, purpose, sent_at)`. Read by:

```
GET /platform/integrations/outbox
```

gated on the **same predicate the resolver already uses** for test doubles —
`TESTING or DEBUG` — and returning 404 otherwise, so there is one definition
of "may fakes run here" rather than two that can disagree.

In memory rather than a table, deliberately: an OTP in plaintext is precisely
what the rest of the authentication module refuses to persist, and this way
there is no migration, nothing survives a restart, and nothing to purge.

The panel renders it as a **Test outbox — development only** card, absent in
production because the endpoint is.

---

## 8. Test send

```
POST /platform/tenants/<id>/integrations/<capability>/test-send
     { "destination": "+9198…" }
```

Deliberately **not** folded into the health check. `health.py` argues
correctly that proving an SMS integration works by sending an SMS charges the
school and rings a real person's phone; a "Test connection" button that
secretly does that is a trap. So health stays free and silent, and this is a
separate, explicitly-labelled action.

- Platform-admin only, like every route in this family.
- The UI says it sends a real, billable message before it is pressed.
- Usage is recorded with `purpose="integration_test"`, so it appears on the
  bill truthfully rather than as an unexplained line.
- Rate-limited on Phase 8's `actor_rate_key` at 5/hour — keyed on the acting
  operator, not the address, for the reason F6 established.
- Uses the same template path as a real send. A test that bypassed templates
  would prove nothing about the case that actually fails.

---

## 9. Lifecycle integrity

Disabling an integration that an enabled authentication method depends on is
**refused**, naming the methods that depend on it.

This is the mirror of the refusal that already exists on the enable side. Its
absence is a live hole: an operator can today switch off a school's SMS and
leave that school showing an OTP button whose codes will never arrive, with
nothing anywhere saying so.

The dependency is derived, not listed — read from the strategy's `is_paid`
declaration and the school's `otp_delivery_channel`, so a future paid method
is covered by declaring itself paid rather than by somebody remembering to
edit a list here.

---

## 10. Panel

### 10.1 `/dashboard/integrations` — new top-level page

The **catalog**: what this build can do, which providers are registered for
each capability, and whether each provider's credentials are present on this
server. Read from the registry, so it describes the deployed code and not
anybody's configuration. No tenant, because none of it is per-school.

This is where an operator answers "can we offer WhatsApp at all yet?" without
opening a school.

### 10.2 Tenant detail → Integrations section

This school's provider for each capability: current provider, status, health
report, configure, enable/disable, test-send, and — in development — the
outbox.

The configuration form has two visually distinct halves, because they are two
different kinds of thing:

- **Settings** — sender ID, template IDs, phone number ID. Non-secret
  identifiers, stored in the integration row, freely displayed.
- **Credentials** — collected as **environment variable names, never values**,
  with the field labelled to say so and showing only whether each name
  currently resolves to something on this server. A pasted secret is refused
  by `configure_integration`; the form should say why before the server has to.

### 10.3 Tenant detail → Login & access becomes writable

- A toggle per (subject kind × method), with its surface.
- Family access mode and student credential policy as controls.
- OTP delivery channel, shown only when `mobile_otp` is enabled for anyone.
- A **readiness banner**: when a method needs a channel that is not ready,
  say which, and link to the Integrations section. The server already refuses
  such a change; the screen should not let it be attempted blind.
- Delete the copy at `login-access-section.tsx:135` — *"Read-only … does not
  yet control who may sign in"*. Phase 8 made that false, and it is currently
  shipping.

All three screens use `useTenantQuery` conventions and prefix invalidation on
mutation, per `.claude/rules/query-conventions.md`.

---

## 11. Migrations

| | Adds | Reversible |
|---|---|---|
| 134 | `tenant_auth_policies.otp_delivery_channel`, default `'sms'` | Yes |

One column, one migration. Existing rows take the default, which is the
behaviour they have today, so the migration changes nothing for anybody until
an operator chooses otherwise.

No migration for the outbox (in memory) and none for providers (a registry
entry in code, plus environment variables).

---

## 12. Tests

Following the existing convention — behavioural names, one file per concern.

| File | Covers |
|---|---|
| `tests/test_messaging_capability.py` | Channel resolution, template refusal, redaction, idempotency, retry-after-timeout policy |
| `tests/test_whatsapp_capability.py` | WhatsApp resolves independently of SMS; a school on one is unaffected by the other's health |
| `tests/test_provider_msg91.py` | Against mocked HTTP: template ID passed, errors normalized, health sends nothing |
| `tests/test_provider_meta_whatsapp.py` | Same, plus variables passed positionally |
| `tests/test_integration_outbox.py` | Fakes record; the endpoint 404s when doubles are not allowed; the buffer is bounded |
| `tests/test_integration_test_send.py` | Billable and recorded as `integration_test`; rate-limited per actor; uses the template path |
| `tests/test_integration_lifecycle.py` | Disabling a depended-on integration is refused and names the methods |
| `tests/auth/test_otp_delivery_channel.py` | The channel is read from policy; changing it while OTP is live is guarded |
| `tests/auth/test_operator_can_switch_it_on.py` | Extended: the readiness gate reads the chosen channel, not SMS |

Panel: component tests for the policy toggles and the readiness banner, and a
test that the outbox card is absent when the endpoint 404s.

**The bar:** every new test must fail against the current tree. A test that
passes before the change it is meant to prove is not evidence.

---

## 13. Out of scope, stated so it is not silently added

- Automatic channel fallback (SMS ↔ WhatsApp).
- Per-school vendor credentials and the encryption-at-rest that would require.
- WhatsApp for fee reminders, attendance, results or announcements. The
  capability makes them possible; each is its own piece of work with its own
  templates and its own consent question.
- Notification template *management* in the panel. Templates are configured
  as IDs on the integration; a template authoring UI is a separate product.
- Debt 58 (`users.email` NOT NULL), still untouched.

---

## 14. The actual critical path: registration

The code does not gate live delivery. This does.

### SMS (DLT, via MSG91)

1. Register the legal entity with a DLT operator (Jio / Airtel / Vodafone
   Idea / BSNL portal). Requires GST or CIN, PAN and an authorised signatory.
2. Register a **sender header** — six characters, e.g. `NEXSCH`. Transactional
   headers are what an OTP must go out under.
3. Register the **content template**, matching `build_otp_message` exactly,
   with the code as a variable. Approval takes days.
4. Create the MSG91 account, link the DLT entity, obtain the auth key.
5. Set the environment variables, configure the school onto `msg91` in the
   panel with the sender ID and template ID, enable, and the method becomes
   enableable — with no code change.

### WhatsApp (Meta Cloud API)

1. Meta Business account, business verification (registration documents).
2. WhatsApp Business Account; add and verify a phone number that is not
   already on the consumer WhatsApp app.
3. Create an **authentication-category** message template with a one-time-code
   variable, and get it approved.
4. Generate a permanent system-user access token — not the 24-hour token the
   quickstart hands out.
5. Set the environment variables, configure, enable.

### Environment variables

| Variable | Used by |
|---|---|
| `MSG91_AUTH_KEY` | `msg91` |
| `META_WHATSAPP_ACCESS_TOKEN` | `meta_whatsapp` |
| `META_WHATSAPP_PHONE_NUMBER_ID` | `meta_whatsapp` |

Sender ID, template IDs and business account ID are **non-secret** and live in
the integration's `configuration`, not in the environment — they are
identifiers, not credentials, and keeping them in the row is what lets two
schools share a vendor account under different templates.

`env.example` gains all three with placeholder values, never real ones.

---

## 15. Sequence

Each step leaves the tree buildable and tested.

1. Rename `SmsSendResult` → `MessageSendResult`; extract `messaging.py` from
   `sms.py`; no behaviour change, existing tests green.
2. `CAPABILITY_WHATSAPP`, `MessagingProvider`, `WhatsAppProvider`.
3. Templates: purpose + variables, refusal when unconfigured.
4. Migration 134, policy read/write, `otp._deliver` on the channel,
   `_method_needs_messaging`.
5. Outbox + fake WhatsApp provider + the dev endpoint.
6. `msg91` and `meta_whatsapp` adapters against mocked HTTP.
7. Test-send route; lifecycle refusal.
8. Panel: writable Login & access (this is what unblocks testing
   `admission_id_password` and `mobile_pin`, which need no provider at all —
   worth landing early).
9. Panel: tenant Integrations section; then the catalog page.
10. Documentation: `docs/modules/integrations.md`, `identity-domain.md`,
    the debt register, and an ADR for the no-fallback decision.

---

## 16. Risks

**The abstraction is wrong and the first real adapter reveals it.** Mitigated
by writing both real adapters this phase rather than deferring them — which is
why step 6 is before the screens and not after.

**A school is switched onto a channel whose template is missing**, and every
OTP fails at send time. Mitigated by refusing the send before the provider is
called, and by the readiness banner.

**Fakes reachable in production.** Mitigated by there being one predicate, in
`resolver.py`, that both the resolver and the outbox endpoint consult — and a
test that asserts the endpoint 404s when it is false.

**The rename touches a lot of files at once.** Mitigated by it being step 1,
mechanical, and covered by tests that already exist and must stay green.
