# ADR-023 — A Subscription Has a Term, a Grace Period, and a Paper Trail

## Status

Accepted

---

## Date

2026-09-13

---

# Context

A school's subscription state was a single word on the tenant — `trial`,
`active`, `suspended` — set by hand from the panel. Nothing recorded when a
subscription began or when the next payment was due, so "is this school paid
up?" could only be answered from memory or from a spreadsheet outside the
product, and a school that stopped paying stayed `active` until an operator
noticed. Nothing recorded what a school had paid either: NexSchool has no
invoices and no payment gateway, schools pay by bank transfer, UPI, cheque or
cash, and the only trail was the bank statement.

# Decision

**The term lives on the tenant.** `subscription_starts_on` and
`subscription_due_on` are dates; `grace_days` (default 7) is how long the
school keeps working after the due date; `auto_suspend_after_grace` (default
on) says whether the platform suspends the school itself when grace runs out.
A null due date means no term has been set, and such a school is never
suspended by this rule — so existing schools change nothing on deploy.

**Standing is derived, never stored.** `modules/subscription/term.py` is the
one place that answers where a school is in its term: *current* through the
due date, *payment due* through the last day of grace, *grace expired* from
the day after. The write gate (`core/decorators/subscription.py`), the nightly
job, the panel and the school's own screen all read that one function, so
they cannot disagree.

**The gate fails closed on its own; the job writes it down.** The moment
grace ends the write gate refuses writes (`GracePeriodExpired`), whether or
not anything has flipped `status`. The nightly task
`subscription.suspend_after_grace` then sets `status = suspended` for schools
that have not opted out, so the panel, the banner and the audit trail say the
same thing the gate already does. A school that opted out stays `active` in
the panel but is still refused writes; suspension is then the operator's
call.

**A payment is a record, not a transaction.** `subscription_payments` holds
what the operator wrote down: amount, date paid, method, reference, the
period covered, a note, who recorded it. A payment is never edited or
deleted; a wrong one is voided with a reason and stays on the list, struck
through, so the school and the operator always see the same trail.
Recording a payment with a `next_due_on` is how a renewal is done: the due
date moves on, the start date is set if it never was, and a school suspended
for non-payment is reactivated. A payment without one — a part payment —
changes nothing about the term.

**The school reads, NexSchool writes.** The term and the payments are shown to
the school behind `subscription.read`, the same gate as the bill. There is no
school-side write.

**A suspended school can still see its account.** Suspension used to mean the
tenant did not resolve at all: its own login answered "tenant not found".
That was tenable while only an operator ever suspended a school. Once the
platform suspends schools itself for non-payment, it is the worst thing to
show them, so `core/tenant.py` lets a suspended tenant resolve and reach
`/api/auth/*` and `/api/subscription*` — and nothing else. It took four
changes, because "suspended means gone" had been written down in four
places: the tenant lookup filtered on `status=active`, the middleware
refused every path, the email sign-in strategy dropped accounts in a
suspended school, and refresh-token rotation ended the session. A **deleted**
tenant is unchanged and reaches none of it.

**The school is reminded every day, and cannot switch the reminder off.**
`subscription.send_payment_reminders` runs daily and writes to every
administrator of a school with an outstanding payment, in the app and by
email, from `REMINDER_WINDOW_DAYS` (7) before the due date until the term
moves on — through the grace period and past it, because a suspended school
is the one that most needs telling. `tenants.last_payment_reminder_on` makes
it once a day rather than once a run. Two things had to give way for this to
actually arrive: `notifications` is a feature a school can turn off, and the
email strategy refuses any type it has no template row for. Both are correct
for a school's own modules and wrong for a notice about money owed, so
`PLATFORM_ACCOUNT_NOTIFICATIONS` names the types that bypass them. A school
being suspended without ever being told is not an acceptable failure.

# Consequences

- Suspension for non-payment becomes a rule, not a memory. The one-week
  default was chosen because a bank transfer in India can take a few working
  days to reconcile and an operator needs time to record it.
- The `status` column is now a statement about the account, not a summary of
  its billing standing: `active` plus an expired grace is a refused school.
  Readers that want "may this school write?" must ask the gate, not the column.
- Trials are untouched: `trial_ends_at` still governs a `trial` school.
- A person who works at two schools, one suspended, is now offered both in
  the sign-in chooser instead of being signed straight into the paid one.
  That is the point — the administrator of the school in arrears is exactly
  who has to go and look at it.
- `suspended` no longer means "no access". Anything that reads the column to
  decide whether somebody may act must ask the subscription gate instead.
- What is deliberately not built: invoices, reminders before the due date,
  and proration. A reminder email a few days before `subscription_due_on` is
  the obvious next step and would read the same standing function.

# Alternatives considered

- **Suspend by hand only.** Rejected: the failure mode is a school that
  stopped paying months ago and nobody noticed.
- **Suspend the moment the due date passes.** Rejected: a bank transfer sent
  on time can land after the date; punishing that is a support call with
  no upside.
- **Store standing as a column.** Rejected: it would be one more thing to
  keep in step with the dates, and a stale value here is a school locked out
  or let through wrongly.
