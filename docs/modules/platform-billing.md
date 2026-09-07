# Platform Billing

What a school pays NexSchool, and what NexSchool pays to serve it.

> Not to be confused with **fees** (`modules/fees`, `modules/finance`), which
> are a school billing its own parents. The two share the word "invoice" and
> nothing else — no foreign key, no shared calculation, no shared code path.

---

# Purpose

NexSchool charges a school for two different kinds of thing.

**The subscription** is what NexSchool has always charged: a rate per student
per year, optionally discounted over a date window. One rate, one quantity,
one school.

**A third-party service** is something NexSchool buys from somebody else and
the school consumes by the unit — messages, verifications, documents. Here
there are two prices, not one: what the provider charges NexSchool, and what
NexSchool charges the school. They are related by a commercial decision, not
by arithmetic.

---

# Concepts

## Provider

The outside company. NexSchool's relationship with it is NexSchool's, not a
school's, so a provider is **global** — two schools using the same SMS company
do not produce two records that can disagree about its name.

## Service

One thing a provider sells, and the unit it sells it by. A provider may sell
several. The unit is what makes a quantity mean anything: a thousand *of what*.

## Usage

One consumption event. Not a running total — a **ledger**, so that "how much
did this school use between these two dates" has an answer. This is the
difference from `tenant_usage`, which holds one number per school and
overwrites it; a metered service cannot be billed from a counter that forgets.

## Billing component

One line on a school's estimate. The subscription is one; every third-party
service the school uses is another. They add up; none is folded into another.

---

# Provider cost is not customer charge

The two are separate columns, and **neither is ever derived from the other**
except in the one pricing mode that says so by name.

This is not fastidiousness. NexSchool may absorb a cost to win a school, mark
a service up, charge a flat fee whatever the usage, give one school a rate
another does not get, or change provider without telling anybody because the
school's price does not move. A model that stored one number and a margin
would make each of those a schema change.

| Mode | What the school pays |
|---|---|
| `metered` | quantity × the school's unit price |
| `fixed` | a flat annual amount, whatever the usage |
| `pass_through` | exactly what the provider charged — the one mode where they are equal, and equal because the school was told it would be |

**A service key is unique per provider, not globally.** Two vendors can both
sell something keyed `sms`, so a lookup by service key alone has two answers
once a school has two suppliers. `record_usage` and `configure_tenant_service`
take an optional `provider_key` and refuse an ambiguous lookup rather than
resolving it by taking the first row — billing a school at an arbitrary
supplier's rates is worse than failing loudly. (Corrected in Phase 3, when
per-tenant provider selection made the ambiguity reachable; see
`docs/modules/integrations.md`.)

**A school never sees what NexSchool pays.** The tenant-facing payload is put
through `customer_facing()`, which strips cost fields by name wherever they
appear, so a component that later gains a cost field is still safe. Platform
operators see both — that is the screen where somebody decides what to charge.

---

# The annual estimate

An estimate, and it says so in the payload. NexSchool has **no invoices**:
nothing records what a school was actually charged, so there is no document to
mistake this for and the code does not pretend otherwise.

Three separate numbers, each from its own inputs:

- **estimated annual usage** — how much
- **estimated annual provider cost** — what NexSchool will pay for it
- **estimated annual customer charge** — what the school will be billed

Every estimate carries the **basis** it stands on:

| Basis | Meaning |
|---|---|
| `configured` | an operator recorded what this school expects to use in a year |
| `observed` | nobody did, so recent recorded usage was annualised |
| `none` | neither — the honest answer is zero |

An estimate whose provenance is invisible gets read as a bill.

---

# The canonical calculation

There is **one** definition of the money math, in
`modules/billing/calculation.py`. Everything that needs a total consumes it
rather than reimplementing the arithmetic.

Before this it existed three times — in the platform service, in the
tenant-facing subscription route (whose own docstring admitted it was a copy),
and as `revenue_yearly / 12` on the platform dashboard. The first two had
already drifted: only one of them returned the discount window, and they could
disagree about the same school on the same day because one counted students
live and the other read a snapshot refreshed on a best-effort basis.

What the consolidation deliberately did **not** do is make every caller ask
the same question. The platform view counting live and the school's own
dashboard reading its snapshot are both defensible, and both still do it. The
inputs stay each caller's own; only the sum is shared.

    subscription_component(tenant, active_students, on_date)   the subscription
    annual_estimate(tenant_service, ...)                       one service
    annual_statement(subscription, services)                   the year
    monthly_run_rate(annual_total)                             the dashboard tile

`monthly_run_rate` is a twelfth of the annual figure, unchanged from what the
dashboard always showed. It is a run rate, not anybody's bill: nothing in
NexSchool bills monthly, there is no proration, and a school that joined in
November is counted as though it had paid all year.

---

# Tenant isolation

`TenantService` and `ServiceUsageRecord` inherit `TenantBaseModel`, which is
what applies the query scope — a model holding tenant data that does not
inherit it is simply unscoped, however it is annotated. Aggregations filter on
`tenant_id` explicitly as well, because these numbers become money.

The catalog (`ServiceProvider`, `ProviderService`) is deliberately **not**
tenant-scoped. It describes the world, not a school, and it is readable only
by platform administrators.

A school cannot read another school's usage, prices, components or costs, and
cannot read or change its own prices — pricing is a commercial agreement, not
a setting.

---

# Recording usage

A subsystem that consumes a paid service records it and stops:

```python
from modules.billing.usage import record_usage

record_usage(
    tenant_id=tenant_id,
    service_key="sms",
    quantity=1,
    usage_type="sms_otp_sent",
    source="notifications",
    external_reference=provider_message_id,   # when the provider names it
)
```

It never calculates a price. Billing consumes the usage; the emitting feature
does not consume billing.

**Idempotency.** `external_reference` is the provider's own id for the event,
and a second attempt with it is a no-op. The guard is a unique index rather
than a read-then-write, so two workers racing on the same webhook retry still
produce one row. What it deliberately does *not* do is deduplicate rows that
merely look alike: two OTPs to two parents in the same second are two real
messages, and collapsing them would lose usage a provider is going to charge
for. An event with no reference is not deduplicable and is recorded.

**There is no HTTP endpoint that writes usage.** Usage is written by
NexSchool's own subsystems inside a request that is already authenticated and
already tenant-scoped. An endpoint would be a way to write billing data from
outside, and nothing needs one.

---

# API

Platform administrators only, on the existing platform router:

```
GET  /api/platform/service-catalog
POST /api/platform/service-catalog/providers
POST /api/platform/service-catalog/services
GET  /api/platform/tenants/<id>/services
POST /api/platform/tenants/<id>/services
GET  /api/platform/tenants/<id>/annual-statement
```

The school's own view is the existing `GET /api/subscription/state`, which
gained a `services` array behind the `subscription.read` permission that
already guarded its commercials — with provider costs stripped.

---

# Future: how OTP will connect to this

**Not built.** Described here so the next phase does not invent a second
mechanism.

When OTP is implemented it will send a message and record that it did:

```
authentication  →  record_usage(service_key="sms", usage_type="sms_otp_sent")
                        ↓
                   the usage ledger
                        ↓
                   billing calculates
                        ↓
                   a component on the school's estimate
```

The authentication code will never multiply a rate by a quantity. A strategy
that knew a price would mean changing a price requires editing the login path,
and a billing bug becoming a sign-in bug. A test asserts structurally that the
pipeline, the policy and the strategies import nothing from billing and bind
no name that reads like money.

Nothing here presumes SMS. The same mechanism serves an email provider, a
verification provider, a document generator or any other metered API;
authentication is one consumer among future others.
