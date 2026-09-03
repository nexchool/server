# Login Methods & Third-Party Cost Billing — Pre-Design Analysis

**Date:** 2026-09-04
**Status:** Analysis only. No implementation until the open questions below are answered and the design is approved.
**Scope:** `server`, `panel`, `admin-web`, `client`, (`school-erp-infra` for secrets only)

---

## 1. What already exists (verified in code, not assumed)

| Fact | Where | Consequence for this story |
|---|---|---|
| `Session.login_method` column exists, `String(20)`, default `"email"`, **never written to** | `modules/auth/models.py:215`, migration `001` | Free hook. The schema anticipated this story; nothing populates it. |
| `users.email` is **NOT NULL**, `password_hash` **NOT NULL**, unique `(email, tenant_id)` | `modules/auth/models.py:24,50,51` | **The single biggest structural blocker.** Every non-email login method needs an account for a human who has no email. |
| "No email → no login" is a deliberate, documented rule | `modules/students/services.py:335-372`, ADR-003 | Students without email have **no account at all** today. Admission-ID login is not "another way in" — it creates a population of accounts that does not exist yet. |
| Cross-tenant login: with no tenant in the request, login searches **all** tenants and returns `requires_tenant_choice` | `modules/auth/routes.py:193-224`, `find_users_by_email_password` | One mobile app for all schools. Any new identifier inherits this path — and admission numbers/phone numbers collide across tenants far more than emails do. |
| Failed-login lockout + rate limit exist | `failed_login_count`, `login_locked_until`, `@limiter.limit("5 per minute")`, `record_failed_login`, `max_login_attempts` | Reusable, but OTP needs *different* throttles (locking a phone number is a DoS vector, and each attempt costs money). |
| Platform super-admin god-login into any tenant with own credentials | `routes.py:150-176`, `authenticate_platform_admin` | Must survive the refactor. A tenant on "OTP only" must not lock out the super admin. |
| Student initial password pattern **already implemented**: first 3 letters of name + birth year, with `force_password_reset=True` | `generate_student_password`, `modules/students/services.py:352-358` | Conflicts with the pattern proposed in this story (DOB + initials + academic year). One of them has to go. |
| Billing is **derived, not stored**: `active_students × price_per_student_per_year − discount` | `modules/platform/services.py:585` (`calculate_tenant_billing`), `modules/subscription/routes.py:_bill_summary` | There is **no invoice table, no line items, no cost catalog**. "Add OTP cost as a separate component and show a total" requires a new billing-components model, and there are currently **two** copies of the bill maths that must not diverge. |
| `tenants.feature_flags` JSON doubles as a per-tenant **settings bag** (`login_variant` lives there as a string) | `core/feature_flags.py:88-92`, `routes.py:96` | Precedent exists for per-tenant settings — but see the retired-key landmine (`RETIRED_FEATURE_KEYS`). Login policy is structured data and should **not** go in that bag. |
| **Zero** SMS/OTP/provider code anywhere in the backend | grep: no `otp`, `sms`, `twilio`, `msg91` in `modules/`, `core/`, `shared/` | Method 3 is a greenfield integration, not a modification. |
| `NotificationTemplate.channel` already contemplates SMS, nothing sends it | `modules/notifications/models.py:151` | Once SMS exists, it will immediately be wanted for fee reminders/absence alerts. Meter **SMS units**, not "OTP". |
| Authority comes from **employment**, student access is implied by the Student relationship | ADR-013, migration 087 | There is no single "role" at credential time. "Login method per role" must be re-expressed as "per relationship type". |

### The parent question is already decided

**ADR-011 (Accepted, 2026-08-05) already specifies exactly what this story asks for**: family access is a *per-organization setting* — **"shared with student"** (default; parents are People and Family Members with **no** Account) or **"separate parent login"** (parents get their own Account and a Parent context). Both modes run on the same data model; switching is configuration, not migration.

So that half of the requirement is not a new decision — it is **implementing an accepted ADR**. What is *not* yet decided in ADR-011 is which login *method* a parent account uses, which is a genuinely new question.

---

## 2. Problems with the requirement as written

These are the things I would push back on as architect/product owner before writing a line of code.

### 2.1 "One login method per role" is the wrong axis — people hold several roles

A teacher whose child studies at the same school. A principal who is also a parent. A Grade-11 student who is also a school-employed sports assistant. If students use admission-ID and staff use email, what does she use?

The identity domain's own security principle is **"One Person owns at most one Account."** Forcing method-by-role produces either two accounts for one human (violates it) or an unanswerable question.

**Recommendation:** methods are **identifiers attached to one account**, and the tenant policy declares which identifier types may be *issued* to which relationship — not which credential a human is forced to use. Login accepts any identifier the account holds and the tenant permits. This is also the only shape that survives the next method (Google SSO, ABC ID, government ID) without another refactor.

### 2.2 Method 4 (mobile number as both ID and password) is not a login method

Anyone who knows the number is in. Phone numbers of an entire class circulate in WhatsApp groups, and the number is *inside the product itself* as an emergency contact, visible to staff. Siblings share one number, so it does not even identify a single account.

It is offered by competitors, so I am not going to pretend it is unavailable — but it should be:
- opt-in per tenant with an explicit recorded acknowledgement of the risk (who enabled it, when),
- never available to staff, admin or anyone holding write permissions,
- excluded from any account that can see fee/financial data if that is a concern,
- hard-throttled and audited.

**Cheaper alternative worth considering:** mobile number as the ID + a **4/6-digit school-issued PIN** as the secret, forced to change on first use. Same UX (no email, no password to remember, no SMS cost), an actual secret.

### 2.3 A derivable password is not a password

DOB + initials + academic year is known to every classmate. It is acceptable **only** as an *initial* credential with `force_password_reset=True` (which the codebase already does). It must never be the standing scheme.

Also: if the academic year is embedded, does the password change at year rollover? If yes, 15,000 students are locked out every June. Assume it does not, and that the year is only in the *issued* value.

### 2.4 "Estimate the yearly OTP cost at enable time" is the wrong billing shape on its own

OTP volume is consumption, not a subscription. An estimate is right for the **quote**; you also need **actuals**, or the estimate is never checked against reality and the margin is invisible.

**Recommendation:** model both — an estimated annual add-on line for the bill/quote, and a metered `sms_usage` counter so estimate vs. actual is visible in the panel.

### 2.5 India-specific blocker the requirement does not mention: **TRAI DLT**

Transactional SMS in India cannot be sent without a DLT-registered entity, sender ID (header) and pre-approved templates. That is registration cost, lead time (days to weeks), and a per-template approval workflow. It is a hard prerequisite for method 3, not a detail. WhatsApp Business API has its own per-conversation pricing and template approval.

### 2.6 The OTP endpoint is an endpoint that spends money

Absent from the requirement and, in my view, the highest-severity gap: an unauthenticated endpoint that sends a paid SMS per call. Without caps, one attacker with a script runs up an uncapped bill against a tenant you may have chosen not to charge.

Mandatory before method 3 ships: per-phone cooldown, per-phone daily cap, per-IP cap, **per-tenant daily spend cap with automatic cutoff**, and alerting. Plus: silent success responses so the endpoint cannot be used to enumerate which numbers are registered.

---

## 3. Edge cases

### Identity & identifier collisions
1. Two siblings, one parent phone → phone resolves to N accounts. Needs a "which child?" chooser mirroring the existing "which school?" chooser.
2. One phone across two tenants (trust with two schools; a teacher at A who is a parent at B).
3. Same phone as a student's contact *and* a staff member's contact.
4. Admission number is unique per tenant only — a cross-tenant admission-ID login is impossible without the school being named first. The mobile app's "one app for all schools" flow must therefore ask for the school **before** the admission number, or resolve by subdomain.
5. Admission-number formats: leading zeros, campus prefixes, slashes, re-use after a student leaves, duplicates introduced by bulk import.
6. Phone normalisation: `+91`, `0`, spaces, 10 vs 13 digits. Must be stored E.164 and matched normalised, or "the number that works on my dad's phone" becomes a support queue.
7. A person changes their phone number → their credential changes. Who may change it, and does it require verification of the new number?
8. Student promoted / transferred campus / graduated — does the credential survive? Should a graduated student be able to log in to see their marksheet?
9. A soft-deleted account's identifier: the current unique constraint is not scoped to `deleted_at`, so identifiers inherit the same "email is not reusable" trap. Decide deliberately for each identifier type.

### Policy & lifecycle
10. Tenant switches policy mid-year: are existing sessions revoked, do existing passwords still work, is there a grace period? (Policy must be additive by default.)
11. Tenant enables "separate parent accounts" for a school that has been running shared — 2,000 accounts must be minted, and every parent notified. That is a batch job with a notification cost, not a checkbox.
12. Tenant *disables* separate parent accounts — do parent accounts get deleted, suspended, or kept dormant? (Data-retention question.)
13. A parent of three children in the school — one account, three student contexts. Active Context (ADR-004) is currently **deferred** because "nearly everyone holds exactly one context". Turning on parent accounts un-defers it.
14. Super admin god-login into a tenant whose policy is "OTP only" — must still work via email/password.
15. Platform maintenance mode + OTP: do not charge for an SMS that leads to a 503.

### OTP-specific
16. SMS not delivered (carrier, DND registry, out of coverage) → fallback path: resend, alternate channel (WhatsApp/email), or "contact your school".
17. Same OTP requested twice — is the previous one invalidated? (It must be, or a stolen older code stays live.)
18. OTP expiry, max verify attempts, replay after successful use, and the timing-safe compare.
19. User changes SIM/number and can no longer receive OTP and has no other credential → complete lockout. Needs an admin-side recovery path.
20. Number ported / recycled by the carrier to a stranger → the stranger can log in as the student. Real, and a reason to require re-verification periodically.
21. DND / promotional-vs-transactional classification causing silent non-delivery.
22. OTP in a school with poor connectivity, or a student whose only device is the parent's phone at work.

### Operational / cross-cutting
23. Existing users must not be locked out by any change — every policy defaults to today's behaviour (email + password) until explicitly changed.
24. JWT currently carries an `email` claim; accounts with a null email break it. Same for anything displaying `user.email` in `admin-web`/`client`.
25. Bulk import (`bulk_student_import_service.py`, `bulk_teacher_import_service.py`) creates users and must learn to create identifiers.
26. Seed/demo data (`seed_demo_data.py`, `seed_school.py`) must produce accounts under the new model or local dev diverges from prod.
27. Audit: which method and which identifier was used, per login. Currently nothing records it.
28. Shared-account attribution (ADR-011's known trade-off) gets worse under phone-as-password, since more than one household member has the credential.
29. DPDP Act / minors: storing and using a child's phone number as a credential, and consent for SMS.
30. Prod migration lag is a known past incident on this project — a 6-to-9 migration story needs deliberate deploy sequencing.

---

## 4. Areas the requirement did not cover

1. **Credential administration UI.** Who resets a student's password when the student has no email and no phone? Today's flows are email-token based. This story needs an admin screen: view identifiers, reissue credential, print/export credential slips for a class, force reset. This is arguably as much work as the auth itself, and schools will ask for it on day one.
2. **Bulk credential issuance.** 2,015 students at one tenant. Credentials must be generated, exported (PDF/CSV per class) and handed out. That is the actual onboarding workflow.
3. **First-login experience.** Forced password change already exists for students; it must be extended to the new methods and to parents.
4. **What happens to `admin-web` for non-staff.** Do students/parents ever use the web app, or is the mobile app their only surface? This decides whether the web login page needs any of methods 2–4 at all.
5. **SMS beyond OTP.** Once a provider is integrated, fee reminders and absence alerts will want it immediately. Meter SMS units, not the OTP feature, or you rebuild the metering in a month.
6. **Email OTP and WhatsApp OTP** — both materially cheaper than SMS; email OTP is free and works for staff.
7. **A generic third-party integration model.** The panel page you describe should not be an "OTP page". It should be an integrations catalog (provider, unit, unit cost, tenant enablement, usage) so payment gateways, WhatsApp, storage, and AI features slot in later. Otherwise you build this page again per integration.
8. **Currency, tax and rounding** on the added billing components (GST on the SMS pass-through?).
9. **Who is allowed to see the cost.** `subscription.read` already gates commercials from teachers — new components must respect the same gate.
10. **The exit path.** Tenant disables OTP mid-year: is the estimated annual line pro-rated or dropped?
11. **SSO / Google login** — not in this story, but the identifier model should not preclude it. It is the cheapest method to add later and the one international schools ask for.
12. **Device binding / trusted device**, so OTP is not charged on every single login (this directly controls the cost). The requirement says "each time while login" — that is the most expensive possible choice.

---

## 5. Recommended architecture (for discussion, not yet approved)

**Core move: replace "email + password on the user row" with "an account holds identifiers, and the tenant's policy says which identifiers may be issued and used."**

```
Person (People domain)
  └── Account (Identity domain)            # one per person, ADR-003
        ├── AccountIdentifier[]            # NEW: (type, value) unique per tenant
        │     email | admission_number | mobile | employee_code | ...
        ├── AccountCredential[]            # NEW: password / pin (a secret, not an identifier)
        └── Session[]                      # existing; finally populate login_method
```

- `AuthMethod` strategies (`email_password`, `identifier_password`, `mobile_otp`, `mobile_as_password`), each a small independent unit: *given a submitted identifier, find candidate accounts; given a secret or challenge, verify*. Login becomes one pipeline over a registry of strategies rather than 140 lines of branching.
- `TenantAuthPolicy` — a real table (not the `feature_flags` bag): per relationship type (student / staff / parent), which methods are permitted, plus `family_access_mode` from ADR-011.
- `OtpChallenge` + an `SmsProvider` adapter behind an interface, with the provider chosen by config.
- `Integration` / `TenantIntegration` catalog with unit cost, and `calculate_tenant_billing` returning **components** (`base`, `discount`, `add_ons[]`, `total`) from **one** implementation that both the panel and `/api/subscription/state` call — closing the existing duplicate-bill-maths debt in the same change.

**Why this is safe:** email becomes identifier type `email`, backfilled from `users.email`. Every existing login keeps working unchanged. Policy defaults to email-only, which is exactly today's behaviour. Each new method is additive and dark until a tenant opts in.

### Suggested phasing

| Phase | Content | External cost | Risk |
|---|---|---|---|
| 0 | Identifier + credential model, policy table, strategy registry, backfill. **Zero user-visible change.** | none | med (touches auth) |
| 1 | Admission-number + password for students; credential issuance/reset/export admin UI | none | low |
| 2 | Parent accounts (implements ADR-011 mode B) + Active Context un-deferred | none | med |
| 3 | Integrations catalog + billing components + usage metering (**no SMS yet — model the money first**) | none | low |
| 4 | Mobile OTP: provider, DLT registration, throttles, spend caps | yes | high |
| 5 | Mobile-as-password (only if a customer demands it) | none | security |

---

## 6. Scope, effort, risk

**Files touched (estimate):**

| Repo | Work | Files | Migrations |
|---|---|---|---|
| `server` | identifier/credential model, policy, strategy registry, login refactor, OTP domain, SMS adapter, integrations catalog, billing components, parent accounts, bulk issuance, tests | 25–35 | 6–9 |
| `panel` | Login & Access tab per tenant, Third-party integrations page, billing components in the bill preview | 8–12 | — |
| `admin-web` | policy-aware login page, credential administration screens, forced-reset flow | 10–15 | — |
| `client` (Expo) | multi-method login, OTP entry + resend timer, school chooser + child chooser | 10–15 | — |
| `school-erp-infra` | provider secrets/env | 1–2 | — |
| **Total** | | **~60–90** | **6–9** |

**Effort:** ~3–5 focused weeks for the full scope. Phases 0+1 alone are ~1.5 weeks and deliver most of the customer-visible value with no external cost and no new vendor.

**Difficulty: high.** Not because any single piece is hard, but because it is the one module every request passes through, it contains subtle security code (cross-tenant lockout counting, god-login precedence), and a regression is a total outage or a cross-tenant leak.

**Is it safe? Yes, if phased as above; no, if `users.email` is made nullable in one shot.** Concretely, the things that break if this is done carelessly:

- `User.get_user_by_email`, the `(email, tenant_id)` unique constraint, `find_users_by_email_password`, `accounts_for_email`
- JWT `email` claim and everything downstream that reads it
- Password reset / email verification (both assume an email exists)
- Bulk student & teacher import, `seed_demo_data.py`, `seed_school.py`
- Every `admin-web` / `client` screen that displays `user.email`
- The lockout + rate-limit interplay on the cross-tenant search path (security-sensitive, easy to regress silently)
- `feature_flags` retired-key landmine, if login policy is stored in that bag

Mitigation: keep `users.email` populated and NOT NULL through phases 0–1; introduce identifiers alongside it; only relax the column once every read path goes through the identifier table.

---

## 7. Open questions

Grouped; answers to these determine the design.

### A. Product & policy
1. Is the login method chosen **per tenant** (one method for the whole school) or **per relationship type within a tenant** (students by admission ID, staff by email, in the same school)? The requirement implies the latter — confirm.
2. Can a tenant enable **several** methods at once (student may use admission ID *or* email), or is it exactly one per group?
3. If a person holds two relationships (teacher who is also a parent), do they get one account with two identifiers, or two accounts? (Recommendation: one account, and this is what ADR-003 requires.)
4. Do students and parents ever log into **admin-web**, or is the mobile app their only surface? If mobile-only, methods 2–4 never need a web login page.
5. Do staff *ever* get a non-email method, or is email+password permanently the staff answer? (Requirement says the latter — confirm it holds for sub-admins and principals too.)
6. What is the default policy for a **newly onboarded** tenant, and for the **existing** tenants on prod?
7. When a tenant changes policy mid-year: additive only, or can a method be removed? Are sessions revoked?

### B. Student credentials (method 2)
8. Confirm the exact initial-password pattern. `generate_student_password` today is *first 3 letters of name + birth year*. Your story says *DOB + initials in caps + academic year*. Which wins, and do existing students get re-issued?
9. Is the pattern an **initial** password with forced change on first login (recommended), or the standing password?
10. If the school wants forced change **off** (many will, to reduce support calls), do we allow that?
11. Admission number as identifier: is it guaranteed unique and stable per tenant in your data today, including after bulk imports? Does it change on campus transfer or promotion?
12. In the mobile app (one app, all schools), how does a student identify the school before entering an admission number — subdomain, school picker, or a school code printed on the credential slip?
13. Should a **graduated / withdrawn** student retain login (to view marksheets), and for how long?
14. Who resets a student's forgotten password when there is no email and no phone — class teacher, admin only, or a printed slip reissue?

### C. Mobile / OTP (methods 3 and 4)
15. Is OTP available to **all** roles or students/parents only?
16. OTP on **every** login, or only on a new device with a trusted-device period (30/60/90 days)? This is the single biggest lever on cost.
17. Which SMS provider — MSG91, Gupshup, Twilio, Kaleyra, other? Is there an existing account?
18. Is DLT registration (entity ID, header, templates) already done, or is that part of this project's scope and timeline?
19. Should **email OTP** and/or **WhatsApp OTP** be supported as cheaper channels, with SMS as fallback?
20. Whose phone number is it for a student — the student's own, or the household number from the guardian fields? What happens when siblings share one?
21. Where does the authoritative phone number live — `persons.phone_number`, or the `father_phone` / `mother_phone` / `guardian_phone` columns on `students`? (They currently disagree.)
22. On method 4 (number as ID *and* password): do you want it at all, given section 2.2? Would mobile + school-issued PIN be acceptable instead?
23. If method 4 stays: is it students-only, and must the tenant record an explicit acknowledgement of the risk?
24. Per-tenant OTP spend cap: what is the default daily/monthly ceiling, and what happens when it is hit — block logins, or fall back to password?

### D. Parent accounts
25. ADR-011 already decides this ("shared with student" default, "separate parent login" optional). Confirm we are implementing ADR-011 rather than designing something new.
26. In separate-parent mode, what does a parent account see that the student account does not, and vice versa? Is there any content we must keep away from the student?
27. One parent, three children — one account with a child switcher, or one account per child?
28. Both parents want separate logins — one parent account per Family Member, or one per family?
29. When separate mode is switched on for an existing school, do we mint accounts for all parents at once and notify them (an SMS/email cost of its own), or issue on demand?
30. Can a school run *mixed* mode (parents for primary grades, students for secondary)?

### E. Billing & third-party costs
31. Is the OTP add-on billed as an **estimated annual amount** fixed at enable time, as **metered actuals**, or estimate-for-quote + metered-for-truth (recommendation)?
32. If estimated: what is the estimation formula? (`students × logins/student/year × SMS per login × unit cost` — what are your assumed values, and does it include failed sends and resends?)
33. Is the price to the tenant the **cost** (pass-through), cost + markup, or an internal-only figure we may choose not to charge? The requirement says "our call" — should the panel hold both an internal cost and a chargeable price?
34. Where does the number appear — panel only (internal), or also on the tenant's own subscription screen in `admin-web`?
35. Mid-year enable/disable: pro-rated, or full-year either way?
36. GST/tax and currency on add-on components — any handling needed now?
37. Should the integrations catalog be **generic** (payment gateway, WhatsApp, storage, AI, all with unit costs) or OTP-specific for now? (Recommendation: generic; the shape costs nothing extra today.)
38. There are currently **two** implementations of the bill (`calculate_tenant_billing` and `_bill_summary`). Approve consolidating them into one as part of this work?

### F. Sequencing & delivery
39. Do you accept the phasing in section 5, and specifically that **phase 0 ships with no user-visible change**?
40. Is this v2-program work on `develop`, or does any of it need to reach prod on `main` sooner?
41. Auth is currently REST. The v2 rule is "GraphQL is the primary business API, REST is infra only". Is authentication *infra* (stays REST) or *business* (moves to GraphQL) for this work?
42. Do you want the credential-administration and bulk-issuance UI in scope now, or as a follow-up? (Schools will need it the day phase 1 ships.)
43. Which tenant is the pilot for the first non-email method?

---

## 8. Recommendation in one paragraph

Do not build four login methods. Build **one identity model that has identifiers and a policy**, then light up methods against it one at a time. Phase 0 and 1 (identifier model + admission-ID login + credential administration) deliver almost all of the customer value, cost nothing external, and are reversible. ADR-011 already answers the parent question, so that is implementation rather than design. The billing work should be modelled as a **generic third-party integrations catalog with metered usage**, built *before* the SMS provider so the money is understood before it is spent — and OTP must not ship without a per-tenant spend cap, because it is an unauthenticated endpoint that spends real money on every call.
