# Authentication Phase 9 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give operators a way to switch sign-in methods on, give schools a second messaging channel, and make `mobile_otp` testable end to end without a vendor account.

**Architecture:** The capability layer generalizes from `sms` to messaging (`sms` + `whatsapp`), messages become a purpose plus variables resolved against a per-school registered template, OTP reads its channel from the school's authentication policy, and the panel gains the screens that operate all of it. Nothing in `modules/integrations/` is redesigned — the registry, resolver, health, credential-reference and usage-recording decisions all stand.

**Tech Stack:** Flask 3 / SQLAlchemy 2 / Alembic (`server/`), pytest. Next.js 16 / React / TanStack Query v5 / Tailwind 4 / shadcn-ui (`panel/`). Vitest 4 + Testing Library for panel tests (added in Task 13).

**Spec:** `server/AUTHENTICATION_PHASE_9_DESIGN.md`. Read §1 before starting — most of this phase's backend already exists and must not be built twice.

## Global Constraints

- **Branch:** all work on `develop` in each repo. Never commit to `main`; a `main` push in `server/` and `panel/` is a real production deploy that runs `flask db upgrade` on boot.
- **Baseline:** `server/` at `431174c` on `develop`. `pytest tests/auth/ tests/test_integrations_foundation.py tests/test_integrations_routes.py tests/test_platform_service_billing.py -q` → **768 passed**. This must stay green after every task.
- **Python interpreter:** `./venv/bin/python -m pytest …` from `server/`. There is no `make test`.
- **House style is load-bearing.** Every module in `modules/integrations/` and `modules/auth/` opens with a docstring explaining *why* the design is what it is, and non-obvious decisions are argued inline. Match it. A file that only says what the code does will read as foreign.
- **Never log a message body, a phone number, or a credential.** `operations.redact_destination` is the only way a destination reaches a log.
- **Credentials are environment variable names, never values.** `credentials.is_valid_reference` enforces the shape; nothing may store, return or log a secret.
- **Health checks never send.** A provider's `health()` may use only free, non-sending endpoints.
- **Every new test must fail before the change it proves.** Run it and see it fail; a test that passes beforehand is not evidence.
- **Naming:** Python `snake_case`; migrations `NNN_a_sentence_about_what_it_does.py`; TS `camelCase`, components `PascalCase.tsx`.
- **Commit format:** `{type}({scope}): {description}`, lowercase, imperative, ≤72 chars. Every commit ends with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Migration head is `133_an_auth_event_says_who_did_it`.** Only Task 5 adds a migration; its `down_revision` is that.
- **Panel queries** follow `.claude/rules/query-conventions.md`. Platform endpoints are *not* tenant-scoped in the query-key sense (a platform admin is not bound to one tenant), so plain `useQuery` is correct there — but the tenant id is still part of the key because the data is per-school.

### Test conventions — read before writing any test

The test snippets in the tasks below are written for clarity and **name
fixtures loosely**. The repository's real conventions are these, and they
govern. Where a snippet says `app`, `platform_admin_client`,
`tenant_admin_client`, `student_with_mobile` or `sms_service_configured`,
translate it as below rather than creating a parallel set of fixtures.

**Fixtures that exist in `tests/conftest.py`:** `flask_app`, `db_session`,
`tenant`, `student`, `student2`, `throttling` (opt-in; the suite is otherwise
un-throttled), plus hostel-domain ones this phase does not use. **There is no
`app` fixture — it is `flask_app`.**

**A test client** is declared per module, as `test_integrations_routes.py`
does:

```python
@pytest.fixture
def client(flask_app):
    return flask_app.test_client()
```

**Authenticating a request** uses header helpers, not client fixtures. Copy
`_platform_admin` and `_school_user` from `tests/test_integrations_routes.py`
(lines 36–55) into any new route-test module — that duplication is the
established pattern here, and every platform-route test module has its own
pair. So `platform_admin_client.post(url, json=…)` means
`client.post(url, json=…, headers=_platform_admin(db_session, tenant))`, and
`tenant_admin_client` means the same with `_school_user(db_session, tenant)`.

**Shared account builders** live in `tests/auth/_characterization.py`:
`make_tenant`, `make_user`, `make_account`, `make_platform_admin`,
`grant_permissions`, `login`, `sessions_for`, `live_sessions_for`,
`decode_access_token`.

**For anything OTP,** do not invent setup. `tests/auth/test_mobile_otp.py`
already has exactly what the tasks below need, and new OTP tests reuse it:

- `_school(db_session, *, otp_enabled=True, sms_working=True)` — a tenant with
  the policy and the fake SMS integration already arranged. This is what the
  plan's `enabled_fake_sms` and `otp_enabled_for_students` fixtures were
  reaching for; extend it with a `whatsapp_working=False` keyword rather than
  adding a second builder.
- `_member(db_session, tenant, *, mobile=None, …)` — an account with a mobile
  identifier issued. This is `student_with_mobile`.
- `_issue(tenant, mobile, **kwargs)` and `_code_for(challenge_id)` — request a
  code and read it back.
- `_reachable_redis` is an **autouse** fixture in that module that skips when
  Redis is not up, because the OTP limiter needs it. Any new module that
  requests an OTP needs the same guard, or it will fail confusingly on a
  machine with no Redis.

**`sms_service_configured`** does not exist and is not a fixture: it means the
billing catalog has an `sms` service, arranged with the helpers in
`tests/test_platform_service_billing.py`. Read that file before writing the
usage assertion in Task 10.

---

## File Structure

**`server/modules/integrations/`**

| File | Responsibility |
|---|---|
| `capabilities.py` | *modify* — add `whatsapp`, `MESSAGING_CAPABILITIES`, its label |
| `base.py` | *modify* — `MessagingProvider` over `SmsProvider`; add `WhatsAppProvider` |
| `results.py` | *modify* — `SmsSendResult` → `MessageSendResult` |
| `templates.py` | **new** — purpose → template id/name, variables, refusal when unconfigured |
| `messaging.py` | **new** — `send_message`: the one resolve → call → normalize → record path |
| `sms.py` | *modify* — becomes a thin `send_sms` over `send_message` |
| `whatsapp.py` | **new** — thin `send_whatsapp` over `send_message` |
| `outbox.py` | **new** — bounded in-memory ring buffer the fakes write to |
| `providers/fake.py` | *modify* — record to outbox; add `FakeWhatsAppProvider` |
| `providers/msg91.py` | **new** — real SMS adapter |
| `providers/meta_whatsapp.py` | **new** — real WhatsApp adapter |
| `registry.py` | *modify* — register the four providers |
| `services.py` | *modify* — disable guard; `describe_capabilities` unchanged in shape |

**`server/modules/auth/`** — `policy_models.py`, `policy.py` (channel), `otp.py` (`_deliver`), `otp_message.py` (variables).

**`server/modules/platform/routes.py`** — `_method_needs_messaging`, outbox route, test-send route, channel in the policy PATCH.

**`server/migrations/versions/`** — `134_which_wire_a_schools_codes_go_down.py`.

**`panel/`**

| File | Responsibility |
|---|---|
| `vitest.config.ts`, `vitest.setup.ts` | **new** — test harness (Task 12) |
| `hooks/useApi.ts` | *modify* — policy mutations, integrations queries/mutations, outbox, capabilities |
| `types/index.ts` | *modify* — integration and capability types; channel on the policy |
| `app/(dashboard)/dashboard/tenants/[id]/login-access-section.tsx` | *modify* — writable |
| `app/(dashboard)/dashboard/tenants/[id]/integrations-section.tsx` | **new** |
| `app/(dashboard)/dashboard/integrations/page.tsx` | **new** — catalog |
| `components/layout/sidebar.tsx` | *modify* — nav entry |

---

## Task 1: Rename `SmsSendResult` to `MessageSendResult`

Mechanical, first, and on its own so that every later diff is about behaviour. `SmsSendResult` is one commit old and has no consumers outside this module plus `otp.py`.

**Files:**
- Modify: `server/modules/integrations/results.py`
- Modify: `server/modules/integrations/base.py`, `sms.py`, `usage_recorder.py`, `providers/fake.py`
- Test: existing suites only

**Interfaces:**
- Consumes: nothing
- Produces: `MessageSendResult` — the dataclass every provider `send()` returns and `messaging.py` normalizes. Fields unchanged: `success, status, provider_message_id, provider_status, error_code, error_message, retryable, billable_units, operation_id, latency_ms`, property `is_billable`.

- [ ] **Step 1: Find every reference**

```bash
cd server && grep -rn "SmsSendResult" --include="*.py" .
```

Expected: `results.py`, `base.py`, `sms.py`, `usage_recorder.py`, `providers/fake.py`, and test files.

- [ ] **Step 2: Rename the class and update its docstring**

In `results.py`, rename the class and change the docstring's first line to describe a message rather than an SMS:

```python
@dataclass
class MessageSendResult:
    """The outcome of asking a provider to send one message, on any channel.

    `status` is the honest one. A provider that only acknowledges receipt gets
    `accepted`, and nothing in this codebase may upgrade that to `delivered`
    without a delivery receipt to stand on.
    ...
    """
```

Leave every field and the `is_billable` property untouched.

- [ ] **Step 3: Update the other references**

```bash
cd server && grep -rl "SmsSendResult" --include="*.py" . | xargs sed -i '' 's/SmsSendResult/MessageSendResult/g'
```

- [ ] **Step 4: Verify nothing is left and the suite is green**

```bash
cd server && grep -rn "SmsSendResult" --include="*.py" . ; ./venv/bin/python -m pytest tests/test_integrations_foundation.py tests/test_integrations_routes.py tests/auth/test_mobile_otp.py -q
```

Expected: grep finds nothing; tests pass.

- [ ] **Step 5: Commit**

```bash
cd server && git add -A && git commit -m "$(cat <<'EOF'
refactor(integrations): name the result for a message, not an SMS

A second channel is arriving and the type is not SMS-specific. Rename
only; no field, no behaviour and no caller semantics change.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: A WhatsApp capability and a provider base that fits both channels

**Files:**
- Modify: `server/modules/integrations/capabilities.py`
- Modify: `server/modules/integrations/base.py`
- Test: `server/tests/test_messaging_capability.py` (create)

**Interfaces:**
- Consumes: `MessageSendResult` (Task 1)
- Produces:
  - `CAPABILITY_WHATSAPP = "whatsapp"`; `CAPABILITIES = (CAPABILITY_SMS, CAPABILITY_WHATSAPP)`; `MESSAGING_CAPABILITIES = CAPABILITIES`
  - `class MessagingProvider(ProviderClient)` — no `send`; holds what both channels share
  - `class SmsProvider(MessagingProvider)` — `send(*, destination, body, template_id, configuration, idempotency_key=None, operation_id=None) -> MessageSendResult`
  - `class WhatsAppProvider(MessagingProvider)` — `send(*, destination, template_name, variables, configuration, idempotency_key=None, operation_id=None) -> MessageSendResult`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_messaging_capability.py`:

```python
"""The capability layer, once there is more than one channel in it."""

from modules.integrations import capabilities
from modules.integrations.base import SmsProvider, WhatsAppProvider
from modules.integrations.registry import registry


def test_whatsapp_is_a_capability_this_build_has():
    assert capabilities.CAPABILITY_WHATSAPP in capabilities.CAPABILITIES
    assert capabilities.CAPABILITY_LABELS[capabilities.CAPABILITY_WHATSAPP]


def test_the_two_channels_are_grouped_as_messaging():
    assert set(capabilities.MESSAGING_CAPABILITIES) == {
        capabilities.CAPABILITY_SMS,
        capabilities.CAPABILITY_WHATSAPP,
    }


def test_a_whatsapp_provider_declares_its_capability_without_being_told():
    assert WhatsAppProvider.capability == capabilities.CAPABILITY_WHATSAPP
    assert SmsProvider.capability == capabilities.CAPABILITY_SMS


def test_the_two_send_signatures_differ_because_the_channels_do():
    """WhatsApp never receives a body. Collapsing these into one `message`
    parameter would hide that, and the hiding is where the bug would live."""
    import inspect

    sms = set(inspect.signature(SmsProvider.send).parameters)
    whatsapp = set(inspect.signature(WhatsAppProvider.send).parameters)
    assert "body" in sms and "body" not in whatsapp
    assert "variables" in whatsapp and "variables" not in sms


def test_the_registry_still_validates_with_a_second_capability():
    registry.validate()
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd server && ./venv/bin/python -m pytest tests/test_messaging_capability.py -q
```

Expected: FAIL — `AttributeError: module has no attribute 'CAPABILITY_WHATSAPP'`.

- [ ] **Step 3: Add the capability**

In `capabilities.py`, below `CAPABILITY_SMS`:

```python
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

CAPABILITY_LABELS = {
    CAPABILITY_SMS: "SMS",
    CAPABILITY_WHATSAPP: "WhatsApp",
}
```

- [ ] **Step 4: Split the provider base**

In `base.py`, replace the `SmsProvider` class with three:

```python
class MessagingProvider(ProviderClient):
    """A provider that delivers a message to a person.

    Holds nothing but the shared identity. It deliberately declares no
    `send`, because the two channels do not take the same arguments and a
    common signature would have to lie about one of them.
    """


class SmsProvider(MessagingProvider):
    """A provider that can send a short message to a phone."""

    capability: str = CAPABILITY_SMS

    @abstractmethod
    def send(
        self,
        *,
        destination: str,
        body: str,
        template_id: Optional[str],
        configuration: dict,
        idempotency_key: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> MessageSendResult:
        """Ask the provider to send one message.

        `body` is the rendered text and `template_id` the registration it
        matches. Under India's DLT regime the second is what makes the first
        deliverable: an operator registers the wording, and every send names
        the registration. A provider outside that regime may ignore it.

        Returns a result rather than raising, including on failure: "the
        message did not send" is an outcome the caller has to handle, not a
        surprise. Only a programming error escapes as an exception.

        `configuration` is the school's non-secret settings. Credentials are
        **not** in it; the client fetches those itself from the environment.
        """


class WhatsAppProvider(MessagingProvider):
    """A provider that can send a WhatsApp template message."""

    capability: str = CAPABILITY_WHATSAPP

    @abstractmethod
    def send(
        self,
        *,
        destination: str,
        template_name: str,
        variables: "list[str]",
        configuration: dict,
        idempotency_key: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> MessageSendResult:
        """Ask the provider to send one template message.

        There is no body. Meta carries an authentication message only through
        a template approved in advance, and the send names that template and
        supplies its variables **positionally** — the order is the template's,
        not ours, so `variables` is a list and not a mapping.
        """
```

Add `CAPABILITY_WHATSAPP` to the import at the top of `base.py`.

- [ ] **Step 5: Run the test and the existing suites**

```bash
cd server && ./venv/bin/python -m pytest tests/test_messaging_capability.py tests/test_integrations_foundation.py tests/test_integrations_routes.py -q
```

Expected: the new file passes. `test_integrations_*` may fail where `FakeSmsProvider.send` no longer matches the abstract signature — fix `providers/fake.py` to take `body` and `template_id` instead of `message`, keeping every behaviour knob as it is.

- [ ] **Step 6: Commit**

```bash
cd server && git add -A && git commit -m "$(cat <<'EOF'
feat(integrations): add a whatsapp capability alongside sms

The two send signatures differ on purpose: WhatsApp never receives a
body, only a template name and positional variables, and one common
signature would have to lie about one channel or the other.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Templates — a purpose and its variables

The requirement that changes the message layer, argued in spec §3: DLT will not deliver an SMS whose body is not a registered template, and Meta will not send an authentication message at all except through an approved one.

**Files:**
- Create: `server/modules/integrations/templates.py`
- Modify: `server/modules/auth/otp_message.py`
- Test: `server/tests/test_message_templates.py` (create)

**Interfaces:**
- Consumes: `errors.CONFIGURATION_ERROR`
- Produces:
  - `TEMPLATE_NOT_CONFIGURED = "template_not_configured"` (added to `errors.py`)
  - `template_for(configuration: dict, purpose: str) -> str` — raises `IntegrationError(TEMPLATE_NOT_CONFIGURED, …)` when absent
  - no OTP purpose constant: `modules/auth/otp_models.py` already owns it as `PURPOSE_AUTHENTICATION`
  - `otp_message.otp_variables(code: str) -> list[str]` — positional, `[code, minutes]`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_message_templates.py`:

```python
"""A message is a purpose and its variables. The template is configuration."""

import pytest

from modules.integrations import templates
from modules.integrations.errors import IntegrationError, TEMPLATE_NOT_CONFIGURED


def test_a_configured_template_is_found_by_purpose():
    configuration = {"templates": {"authentication_otp": "1707169900000000000"}}
    assert (
        templates.template_for(configuration, "authentication_otp")
        == "1707169900000000000"
    )


def test_a_missing_template_is_refused_before_any_provider_is_called():
    """Discovering a missing template from a vendor's rejection code is a
    worse day than discovering it from our own refusal."""
    with pytest.raises(IntegrationError) as raised:
        templates.template_for({"templates": {}}, "authentication_otp")
    assert raised.value.code == TEMPLATE_NOT_CONFIGURED


def test_a_configuration_with_no_templates_key_at_all_is_refused_the_same_way():
    with pytest.raises(IntegrationError) as raised:
        templates.template_for({}, "authentication_otp")
    assert raised.value.code == TEMPLATE_NOT_CONFIGURED


def test_a_missing_template_is_not_retryable():
    """Nobody should retry a configuration problem; somebody should fix it."""
    with pytest.raises(IntegrationError) as raised:
        templates.template_for({}, "authentication_otp")
    assert raised.value.retryable is False


def test_the_otp_variables_are_positional_and_match_the_registered_wording():
    from modules.auth.otp_message import build_otp_message, otp_variables

    variables = otp_variables("418302")
    assert variables[0] == "418302"
    # Whatever wording is registered, the code and the minutes are what it
    # interpolates, and the rendered text has to contain both.
    rendered = build_otp_message("418302")
    assert "418302" in rendered and variables[1] in rendered
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd server && ./venv/bin/python -m pytest tests/test_message_templates.py -q
```

Expected: FAIL — `ModuleNotFoundError: modules.integrations.templates`.

- [ ] **Step 3: Add the error code**

In `errors.py`, after `CONFIGURATION_ERROR`:

```python
#: The school's integration has no template registered for this purpose.
#: A configuration problem, and specifically one that is cheaper to catch
#: here than to learn from a vendor's rejection.
TEMPLATE_NOT_CONFIGURED = "template_not_configured"
```

Add it to `ERROR_CODES` and to `CONFIGURATION_ERROR_CODES`. Do **not** add it to `RETRYABLE_ERROR_CODES`.

- [ ] **Step 4: Write `templates.py`**

```python
"""Which registered template carries a message, and what goes in its slots.

Both channels this build supports refuse free text.

Under India's DLT regime an SMS is delivered only when its body matches a
template registered against the sender's entity, and the send carries that
template's id. Meta will not send an authentication-category WhatsApp
message except through a template approved in advance, and there the send
carries the template's *name* plus its variables positionally — no body at
all.

So a message here is a **purpose** — what it is for — plus the values that
go in its slots. Which template serves a purpose is per-school, per-channel
configuration, stored on the integration row because it is an identifier and
not a secret, and because two schools sharing one vendor account may well
have registered different wordings.

The rendered text has not gone away: it is what an operator submits for
approval, and it is what the fake providers put in the outbox so a developer
reads the real wording. It is simply no longer what is sent.
"""

from __future__ import annotations

from .errors import TEMPLATE_NOT_CONFIGURED, IntegrationError

#: **No OTP purpose constant lives here.** `modules/auth/otp_models.py`
#: already owns that concept as `PURPOSE_AUTHENTICATION`, and it is a stored
#: column value with a server default, a challenge-lookup filter and a billing
#: usage_type. A second name for it here would be a second owner. Callers pass
#: the purpose they own; this module owns only the lookup.

#: Where the map lives on an integration's `configuration`.
TEMPLATES_KEY = "templates"


def template_for(configuration: dict, purpose: str) -> str:
    """The template this school registered for this purpose.

    Raises rather than returning None. A send that reached a provider without
    a template would be refused by the vendor with a code somebody has to
    look up, and would count against a rate limit on the way; refusing here
    costs nothing and says exactly what is missing.
    """
    registered = (configuration or {}).get(TEMPLATES_KEY) or {}
    template = registered.get(purpose)
    if not template:
        raise IntegrationError(
            TEMPLATE_NOT_CONFIGURED,
            f"This school has no template registered for '{purpose}'.",
        )
    return str(template)
```

- [ ] **Step 5: Add `otp_variables` to `otp_message.py`**

Keep `build_otp_message` exactly as it is — it is the canonical record of what gets registered — and add beside it:

```python
def otp_variables(code: str) -> list:
    """The values a registered template interpolates, in its slot order.

    Positional rather than named because that is what both vendors take: DLT
    templates number their variables and Meta's components are an ordered
    list. The order here is the order the wording in `build_otp_message` was
    registered with, and changing one without the other is a re-registration,
    not a code change.
    """
    minutes = max(OTP_TTL_SECONDS // 60, 1)
    return [code, str(minutes)]
```

- [ ] **Step 6: Run the test**

```bash
cd server && ./venv/bin/python -m pytest tests/test_message_templates.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd server && git add -A && git commit -m "$(cat <<'EOF'
feat(integrations): a message is a purpose and its variables

Both channels refuse free text: DLT delivers only a registered body and
Meta only an approved template. A send with no template configured is
refused here rather than by the vendor, which costs a rate limit and an
error code somebody has to look up.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `messaging.py` — one path for both channels

Extracts everything already correct in `sms.py` — one resolution point, one redaction point, one usage-recording point, results rather than exceptions — and makes it channel-agnostic.

**Files:**
- Create: `server/modules/integrations/messaging.py`
- Modify: `server/modules/integrations/sms.py`
- Create: `server/modules/integrations/whatsapp.py`
- Test: append to `server/tests/test_messaging_capability.py`

**Interfaces:**
- Consumes: `resolve_provider`, `template_for`, `record_provider_usage`, `redact_destination`, `new_operation_id`
- Produces:
  - `send_message(*, tenant_id, channel, purpose, destination, variables, body=None, idempotency_key=None) -> MessageSendResult`
  - `sms.send_sms(*, tenant_id, destination, body, purpose, variables, idempotency_key=None) -> MessageSendResult`
  - `whatsapp.send_whatsapp(*, tenant_id, destination, purpose, variables, idempotency_key=None) -> MessageSendResult`
  - `messaging.messaging_health(tenant_id, channel) -> ProviderHealth`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_messaging_capability.py`:

```python
def test_a_send_on_an_unconfigured_channel_returns_a_result_not_an_exception(app, tenant):
    """A caller deciding what to do next should not have to catch anything to
    find out that a school has no provider."""
    from modules.integrations.messaging import send_message

    result = send_message(
        tenant_id=tenant.id,
        channel="whatsapp",
        purpose="authentication_otp",
        destination="+919876543210",
        variables=["418302", "5"],
    )
    assert result.success is False
    assert result.error_code == "configuration_error"
    assert result.billable_units == 0


def test_a_missing_template_stops_the_send_before_the_provider(app, tenant, enabled_fake_sms_without_templates):
    from modules.integrations.messaging import send_message

    result = send_message(
        tenant_id=tenant.id,
        channel="sms",
        purpose="authentication_otp",
        destination="+919876543210",
        variables=["418302", "5"],
        body="418302 is your NexSchool sign-in code.",
    )
    assert result.success is False
    assert result.error_code == "template_not_configured"
    assert result.billable_units == 0


def test_the_channels_resolve_independently(app, tenant, enabled_fake_sms):
    """A school with SMS working and no WhatsApp must not have its SMS
    reported as broken, and vice versa."""
    from modules.integrations.messaging import messaging_health

    assert messaging_health(tenant.id, "sms").ready is True
    assert messaging_health(tenant.id, "whatsapp").ready is False
```

Add the fixtures to `tests/conftest.py` (or the integrations test module, matching where `test_integrations_routes.py` puts its own):

```python
@pytest.fixture
def enabled_fake_sms(app, tenant):
    """A school configured onto the SMS test double, with a template."""
    from core.database import db
    from modules.integrations.services import configure_integration, set_integration_status

    configure_integration(
        tenant.id,
        capability="sms",
        provider_key="fake_sms",
        configuration={"templates": {"authentication_otp": "test-template-1"}},
    )
    set_integration_status(tenant.id, capability="sms", status="enabled")
    db.session.commit()


@pytest.fixture
def enabled_fake_sms_without_templates(app, tenant):
    from core.database import db
    from modules.integrations.services import configure_integration, set_integration_status

    configure_integration(
        tenant.id, capability="sms", provider_key="fake_sms", configuration={}
    )
    set_integration_status(tenant.id, capability="sms", status="enabled")
    db.session.commit()
```

- [ ] **Step 2: Run and watch them fail**

```bash
cd server && ./venv/bin/python -m pytest tests/test_messaging_capability.py -q
```

Expected: FAIL — `ModuleNotFoundError: modules.integrations.messaging`.

- [ ] **Step 3: Write `messaging.py`**

Move the body of `sms.send_sms` across, generalizing the provider call. The docstring keeps the diagram that is currently in `sms.py`.

```python
def send_message(
    *,
    tenant_id: str,
    channel: str,
    purpose: str,
    destination: str,
    variables: list,
    body: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> MessageSendResult:
    """Ask this school's provider for `channel` to send one message.

    `purpose` is what the message is for — `authentication_otp`,
    `fee_reminder`. It
    selects the registered template and becomes the usage record's
    `usage_type`, so a bill can be explained back to the feature that caused
    it.

    `body` is the rendered text, needed by SMS and ignored by WhatsApp, which
    takes only the template name and the variables.

    Returns a result rather than raising, including when the school has no
    provider and when it has no template. A caller deciding whether to tell
    somebody to wait should not have to catch an exception to find out.
    """
    operation_id = new_operation_id()

    if channel not in MESSAGING_CAPABILITIES:
        raise UnknownCapability(channel)

    try:
        resolved = resolve_provider(tenant_id=tenant_id, capability=channel)
        template = template_for(resolved.configuration, purpose)
    except IntegrationError as exc:
        logger.warning(
            "message not sent: %s (tenant=%s channel=%s purpose=%s operation=%s)",
            exc.code, tenant_id, channel, purpose, operation_id,
        )
        return MessageSendResult(
            success=False,
            error_code=exc.code,
            error_message=exc.message,
            retryable=exc.retryable,
            operation_id=operation_id,
            billable_units=0,
        )

    started = time.monotonic()
    try:
        if channel == CAPABILITY_SMS:
            result = resolved.client.send(
                destination=destination,
                body=body or "",
                template_id=template,
                configuration=resolved.configuration,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
            )
        else:
            result = resolved.client.send(
                destination=destination,
                template_name=template,
                variables=list(variables or []),
                configuration=resolved.configuration,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
            )
    except Exception:  # noqa: BLE001 - a client bug must not become a 500
        logger.exception(
            "provider %s raised while sending (tenant=%s operation=%s)",
            resolved.provider_key, tenant_id, operation_id,
        )
        return MessageSendResult(
            success=False,
            error_code="unknown_provider_error",
            error_message="The provider could not be reached.",
            operation_id=operation_id,
            billable_units=0,
        )

    result.operation_id = operation_id
    result.latency_ms = int((time.monotonic() - started) * 1000)

    # Everything a support engineer needs and nothing they must not have: no
    # message body — for OTP that *is* the secret — no credential, and the
    # destination reduced to a correlation key with two digits on it.
    logger.info(
        "%s %s via %s (tenant=%s purpose=%s to=%s operation=%s latency=%dms%s)",
        channel,
        "accepted" if result.success else "failed",
        resolved.provider_key,
        tenant_id,
        purpose,
        redact_destination(destination),
        operation_id,
        result.latency_ms or 0,
        f" error={result.error_code}" if result.error_code else "",
    )

    if result.is_billable:
        record_provider_usage(
            tenant_id=tenant_id,
            capability=channel,
            provider_key=resolved.provider_key,
            result=result,
            purpose=purpose,
        )

    return result


def messaging_health(tenant_id: str, channel: str) -> ProviderHealth:
    """Whether this school's provider for that channel looks usable.

    **Sends nothing**, for the reason `health.py` gives at length.
    """
    from .health import capability_health

    return capability_health(tenant_id=tenant_id, capability=channel)
```

- [ ] **Step 4: Reduce `sms.py` and add `whatsapp.py`**

`sms.py` keeps its module docstring, loses the implementation, and becomes:

```python
def send_sms(
    *,
    tenant_id: str,
    destination: str,
    body: str,
    purpose: str,
    variables: list,
    idempotency_key: Optional[str] = None,
) -> MessageSendResult:
    """Send one SMS. A named surface over `messaging.send_message`."""
    from .messaging import send_message

    return send_message(
        tenant_id=tenant_id,
        channel=CAPABILITY_SMS,
        purpose=purpose,
        destination=destination,
        variables=variables,
        body=body,
        idempotency_key=idempotency_key,
    )
```

`whatsapp.py` is its mirror with `channel=CAPABILITY_WHATSAPP` and no `body`.

- [ ] **Step 5: Run the suites**

```bash
cd server && ./venv/bin/python -m pytest tests/test_messaging_capability.py tests/test_integrations_foundation.py tests/test_integrations_routes.py tests/auth/test_mobile_otp.py -q
```

Expected: PASS. `otp.py` still calls `send_sms`; update its call to pass `body=` and `variables=otp_variables(code)` and `purpose=purpose` (the value `_deliver` already receives).

- [ ] **Step 6: Commit**

```bash
cd server && git add -A && git commit -m "$(cat <<'EOF'
feat(integrations): one send path for both channels

Everything already right about sms.py moves across unchanged: one place
resolves a provider, one place redacts, one place records usage, and a
failure is a result rather than an exception.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: A school chooses its OTP channel

**Files:**
- Create: `server/migrations/versions/134_which_wire_a_schools_codes_go_down.py`
- Modify: `server/modules/auth/policy_models.py`, `policy.py`
- Test: `server/tests/auth/test_otp_delivery_channel.py` (create)

**Interfaces:**
- Consumes: `MESSAGING_CAPABILITIES`
- Produces:
  - `policy_models.OTP_CHANNEL_SMS = "sms"`, `OTP_CHANNEL_WHATSAPP = "whatsapp"`, `OTP_DELIVERY_CHANNELS`
  - `TenantAuthPolicy.otp_delivery_channel` column
  - `policy.otp_delivery_channel(tenant_id) -> str`
  - `policy.set_otp_delivery_channel(tenant_id, channel, *, updated_by_user_id=None) -> TenantAuthPolicy`
  - `policy.describe()` gains `"otp_delivery_channel"`

- [ ] **Step 1: Write the failing test**

Create `server/tests/auth/test_otp_delivery_channel.py`:

```python
"""Which wire a school's sign-in codes go down."""

import pytest

from core.database import db
from modules.auth import policy


def test_a_school_that_has_chosen_nothing_is_on_sms(app, tenant):
    """The default is what every school does today. A migration that changed
    behaviour for anybody would be the wrong kind of surprise."""
    assert policy.otp_delivery_channel(tenant.id) == "sms"


def test_an_operator_can_move_a_school_to_whatsapp(app, tenant):
    policy.set_otp_delivery_channel(tenant.id, "whatsapp")
    db.session.commit()
    assert policy.otp_delivery_channel(tenant.id) == "whatsapp"


def test_a_channel_this_build_cannot_deliver_is_refused(app, tenant):
    with pytest.raises(ValueError):
        policy.set_otp_delivery_channel(tenant.id, "carrier_pigeon")


def test_the_channel_is_in_what_the_panel_reads(app, tenant):
    described = policy.describe(tenant.id)
    assert described["otp_delivery_channel"] == "sms"
```

- [ ] **Step 2: Run and watch it fail**

```bash
cd server && ./venv/bin/python -m pytest tests/auth/test_otp_delivery_channel.py -q
```

Expected: FAIL — `AttributeError: module 'modules.auth.policy' has no attribute 'otp_delivery_channel'`.

- [ ] **Step 3: Add the column to the model**

In `policy_models.py`, beside the other constants:

```python
#: Which channel carries a sign-in code. Not a list of what a school *has* —
#: one choice, deliberately. Automatic fallback between channels doubles the
#: failure modes and the billing explanation for a reliability problem
#: nobody has measured; see ADR-015.
OTP_CHANNEL_SMS = "sms"
OTP_CHANNEL_WHATSAPP = "whatsapp"
OTP_DELIVERY_CHANNELS = (OTP_CHANNEL_SMS, OTP_CHANNEL_WHATSAPP)
```

And on `TenantAuthPolicy`:

```python
    #: Which messaging capability carries this school's sign-in codes.
    #: Defaults to SMS, which is what every existing school gets, so the
    #: migration that adds this changes nothing for anybody.
    otp_delivery_channel = db.Column(
        db.String(20),
        nullable=False,
        default=OTP_CHANNEL_SMS,
        server_default=OTP_CHANNEL_SMS,
    )
```

- [ ] **Step 4: Write the migration**

Create `server/migrations/versions/134_which_wire_a_schools_codes_go_down.py`:

```python
"""Which wire a school's sign-in codes go down.

Adds one column with a default equal to today's behaviour, so every existing
school keeps sending codes by SMS until an operator chooses otherwise. There
is no data to migrate and nothing to backfill.
"""

from alembic import op
import sqlalchemy as sa

revision = "134_which_wire_a_schools_codes_go_down"
down_revision = "133_an_auth_event_says_who_did_it"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tenant_auth_policies",
        sa.Column(
            "otp_delivery_channel",
            sa.String(length=20),
            nullable=False,
            server_default="sms",
        ),
    )


def downgrade():
    op.drop_column("tenant_auth_policies", "otp_delivery_channel")
```

- [ ] **Step 5: Add the read and write to `policy.py`**

```python
def otp_delivery_channel(tenant_id: str) -> str:
    """Which channel carries this school's sign-in codes."""
    policy = policy_for(tenant_id)
    return policy.otp_delivery_channel if policy else OTP_CHANNEL_SMS


def set_otp_delivery_channel(
    tenant_id: str, channel: str, *, updated_by_user_id: str = None
) -> TenantAuthPolicy:
    """Choose the wire, not the method.

    The method stays `mobile_otp` whichever channel carries it. Changing this
    is a routing decision and provisions nothing, revokes nothing and ends no
    session — a code in flight down the old channel is still a valid code.
    """
    if channel not in OTP_DELIVERY_CHANNELS:
        raise ValueError(
            f"Unknown OTP delivery channel {channel!r}. "
            f"Known: {list(OTP_DELIVERY_CHANNELS)}."
        )
    policy = ensure_default_policy(tenant_id, updated_by_user_id=updated_by_user_id)
    policy.otp_delivery_channel = channel
    policy.updated_by_user_id = updated_by_user_id
    db.session.flush()
    return policy
```

Add `"otp_delivery_channel"` to the dict `describe()` returns, defaulting to `OTP_CHANNEL_SMS` when there is no policy row.

- [ ] **Step 6: Run the migration and the tests**

```bash
cd server && ./venv/bin/python -m pytest tests/auth/test_otp_delivery_channel.py tests/auth/test_tenant_auth_policy.py -q
```

Expected: PASS.

- [ ] **Step 7: Verify the migration reverses**

```bash
cd server && ./venv/bin/flask db upgrade && ./venv/bin/flask db downgrade && ./venv/bin/flask db upgrade && ./venv/bin/flask db current
```

Expected: ends at `134_which_wire_a_schools_codes_go_down`.

- [ ] **Step 8: Commit**

```bash
cd server && git add -A && git commit -m "$(cat <<'EOF'
feat(auth): let a school choose which wire its codes go down

One channel, no fallback. Defaults to SMS, so migration 134 changes
nothing for any existing school.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: OTP sends on the chosen channel, and the readiness gate follows

**Files:**
- Modify: `server/modules/auth/otp.py` (`_deliver`)
- Modify: `server/modules/platform/routes.py` (`_method_needs_sms` → `_method_needs_messaging`, and the policy PATCH)
- Test: append to `server/tests/auth/test_otp_delivery_channel.py`; modify `server/tests/auth/test_operator_can_switch_it_on.py`

**Interfaces:**
- Consumes: `policy.otp_delivery_channel`, `messaging.send_message`, `messaging.messaging_health`
- Produces: `routes._method_needs_messaging(method_key) -> bool`; the policy PATCH accepts `otp_delivery_channel`

- [ ] **Step 1: Write the failing tests**

Append to `tests/auth/test_otp_delivery_channel.py`:

```python
def test_a_code_goes_down_the_channel_the_school_chose(app, tenant, enabled_fake_whatsapp, student_with_mobile):
    from modules.auth import otp
    from modules.integrations.outbox import recent

    policy.set_otp_delivery_channel(tenant.id, "whatsapp")
    db.session.commit()

    otp.request_otp(tenant_id=tenant.id, mobile=student_with_mobile.mobile)

    assert recent()[0]["channel"] == "whatsapp"


def test_a_school_on_whatsapp_is_not_blocked_by_a_missing_sms_provider(
    app, tenant, platform_admin_client, enabled_fake_whatsapp
):
    """The current gate checks SMS unconditionally, which would refuse a
    school that does not use SMS at all."""
    policy.set_otp_delivery_channel(tenant.id, "whatsapp")
    db.session.commit()

    response = platform_admin_client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy/methods",
        json={"method_key": "mobile_otp", "subject_kind": "student", "enabled": True},
    )
    assert response.status_code == 200
```

- [ ] **Step 2: Run and watch them fail**

```bash
cd server && ./venv/bin/python -m pytest tests/auth/test_otp_delivery_channel.py -q
```

Expected: FAIL — the second with a 400 naming a missing SMS provider.

- [ ] **Step 3: Point `_deliver` at the chosen channel**

In `otp.py`, replace the `send_sms` import and call:

```python
def _deliver(*, tenant_id, challenge, destination, code, purpose) -> bool:
    """Hand the message to Phase 3, down whichever wire the school chose.

    Marks the challenge `sent` only when a provider accepted it. A provider
    that refused means no code will ever arrive, so leaving the challenge
    verifiable would strand somebody waiting for a message that is not
    coming.
    """
    from modules.integrations.messaging import send_message


    from .otp_message import build_otp_message, otp_variables
    from .policy import otp_delivery_channel

    result = send_message(
        tenant_id=tenant_id,
        channel=otp_delivery_channel(tenant_id),
        purpose=purpose,
        destination=destination,
        variables=otp_variables(code),
        body=build_otp_message(code),
        # One logical send. A retry carrying the same key must not become a
        # second message.
        idempotency_key=f"otp:{challenge.id}",
    )
    ...
```

The rest of the function is unchanged.

- [ ] **Step 4: Make the readiness gate read the channel**

In `routes.py`, rename and generalize:

```python
def _method_needs_messaging(method_key: str) -> bool:
    """Whether turning this method on commits a school to sending messages.

    Read from the strategy rather than a list kept here, so a future paid
    method is covered by declaring itself paid.
    """
    from modules.auth.strategies import registry

    try:
        strategy = registry.get(method_key)
    except Exception:  # noqa: BLE001
        return False
    return bool(getattr(strategy, "is_paid", False))
```

And in `set_tenant_auth_method`, replace the SMS-specific block:

```python
    if enabled and _method_needs_messaging(method_key):
        from modules.auth.policy import otp_delivery_channel
        from modules.integrations.messaging import messaging_health

        channel = otp_delivery_channel(tenant_id)
        report = messaging_health(tenant_id, channel)
        if not report.ready:
            return validation_error_response(
                {
                    "method_key": (
                        f"This method sends a message, and this school has no "
                        f"working {channel} provider. " + (report.detail or "")
                    ).strip()
                }
            )
```

- [ ] **Step 5: Accept the channel on the policy PATCH**

In `update_tenant_auth_policy`, alongside the two existing fields:

```python
    otp_channel = (data.get("otp_delivery_channel") or "").strip()
    ...
        if otp_channel:
            # Moving a school onto a channel it cannot send down would leave
            # an enabled method that silently never delivers. Refused for the
            # same reason enabling the method is.
            if policy.is_method_enabled_anywhere(tenant_id, "mobile_otp"):
                from modules.integrations.messaging import messaging_health

                report = messaging_health(tenant_id, otp_channel)
                if not report.ready:
                    db.session.rollback()
                    return validation_error_response(
                        {"otp_delivery_channel": (
                            f"Mobile OTP is switched on and this school has no "
                            f"working {otp_channel} provider. " + (report.detail or "")
                        ).strip()}
                    )
            policy.set_otp_delivery_channel(
                tenant_id, otp_channel, updated_by_user_id=g.current_user.id
            )
```

Add the helper to `policy.py`:

```python
def is_method_enabled_anywhere(tenant_id: str, method_key: str) -> bool:
    """Whether any rule at this school currently permits that method."""
    return (
        db.session.query(TenantAuthPolicyRule)
        .filter(
            TenantAuthPolicyRule.tenant_id == tenant_id,
            TenantAuthPolicyRule.method_key == method_key,
            TenantAuthPolicyRule.is_enabled.is_(True),
        )
        .first()
        is not None
    )
```

- [ ] **Step 6: Run the auth suite**

```bash
cd server && ./venv/bin/python -m pytest tests/auth/ -q
```

Expected: PASS, including the previously-passing `test_operator_can_switch_it_on.py`.

- [ ] **Step 7: Commit**

```bash
cd server && git add -A && git commit -m "$(cat <<'EOF'
feat(auth): send a code down the channel the school chose

The readiness gate now reads that channel too. It checked SMS
unconditionally, which would have refused a school that uses WhatsApp
and no SMS at all.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: The outbox — reading what a fake sent

The gap that blocks testing `mobile_otp` today: `FakeSmsProvider.send` throws the body away.

**Files:**
- Create: `server/modules/integrations/outbox.py`
- Modify: `server/modules/integrations/providers/fake.py` (record; add `FakeWhatsAppProvider`)
- Modify: `server/modules/integrations/registry.py`
- Modify: `server/modules/platform/routes.py` (the dev endpoint)
- Test: `server/tests/test_integration_outbox.py` (create)

**Interfaces:**
- Consumes: `resolver._test_doubles_allowed`
- Produces:
  - `outbox.record(*, tenant_id, channel, destination, body, purpose) -> None`
  - `outbox.recent(limit: int = 20) -> list[dict]` — newest first, keys `tenant_id, channel, destination, body, purpose, sent_at`
  - `outbox.clear() -> None`
  - `outbox.CAPACITY = 50`
  - `GET /api/platform/integrations/outbox`
  - `FakeWhatsAppProvider(key="fake_whatsapp")`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_integration_outbox.py`:

```python
"""What a test double sent, readable only where test doubles may run."""

from modules.integrations import outbox


def test_the_buffer_is_bounded(app):
    """An unbounded in-memory collection is a memory leak with a schedule."""
    outbox.clear()
    for index in range(outbox.CAPACITY + 10):
        outbox.record(
            tenant_id="t", channel="sms", destination="+91987654321",
            body=f"message {index}", purpose="authentication_otp",
        )
    assert len(outbox.recent(limit=1000)) == outbox.CAPACITY


def test_the_newest_message_is_first(app):
    outbox.clear()
    outbox.record(tenant_id="t", channel="sms", destination="+9198", body="first", purpose="authentication_otp")
    outbox.record(tenant_id="t", channel="sms", destination="+9198", body="second", purpose="authentication_otp")
    assert outbox.recent()[0]["body"] == "second"


def test_a_fake_send_reaches_the_outbox(app, tenant, enabled_fake_sms):
    from modules.integrations.sms import send_sms

    outbox.clear()
    send_sms(
        tenant_id=tenant.id, destination="+919876543210",
        body="418302 is your NexSchool sign-in code.",
        purpose="authentication_otp", variables=["418302", "5"],
    )
    assert "418302" in outbox.recent()[0]["body"]


def test_the_endpoint_is_absent_where_test_doubles_may_not_run(app, platform_admin_client):
    """One predicate decides whether fakes run and whether their outbox can
    be read. Two that could disagree is how a fake reaches production."""
    app.config["TESTING"] = False
    app.config["DEBUG"] = False
    try:
        response = platform_admin_client.get("/api/platform/integrations/outbox")
        assert response.status_code == 404
    finally:
        app.config["TESTING"] = True


def test_the_endpoint_needs_a_platform_admin(app, tenant_admin_client):
    response = tenant_admin_client.get("/api/platform/integrations/outbox")
    assert response.status_code in (401, 403)
```

- [ ] **Step 2: Run and watch it fail**

```bash
cd server && ./venv/bin/python -m pytest tests/test_integration_outbox.py -q
```

Expected: FAIL — `ModuleNotFoundError: modules.integrations.outbox`.

- [ ] **Step 3: Write `outbox.py`**

```python
"""What a test double pretended to send, so a developer can read it.

A fake provider that returns a reference and throws the message away makes
`mobile_otp` untestable: the code exists, it is valid for five minutes, and
nothing anywhere can tell you what it is. This is the smallest thing that
fixes that.

**In memory, and bounded.** A table would mean a migration, a purge job, and
an OTP in plaintext at rest — which is precisely what the rest of the
authentication module refuses to have. A ring buffer that does not survive a
restart is the right amount of durability for something whose only reader is
a developer with the application running in front of them.

**Not reachable in production.** The endpoint that reads this consults
`resolver._test_doubles_allowed`, the same predicate that decides whether a
fake may run at all. One predicate rather than two that can disagree.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Dict, List

from core.school_time import utc_now

#: How many messages to keep. Enough to debug a flow, few enough that this
#: cannot grow into a memory problem in a long-running development server.
CAPACITY = 50

_messages: deque = deque(maxlen=CAPACITY)
_lock = threading.Lock()


def record(*, tenant_id: str, channel: str, destination: str, body: str, purpose: str) -> None:
    """Keep what a fake provider was asked to send.

    Called only from the fake providers. A real provider must never call
    this: the body of a real OTP is a live secret, and the whole argument for
    keeping this in memory rests on it only ever holding fictional ones.
    """
    with _lock:
        _messages.appendleft(
            {
                "tenant_id": tenant_id,
                "channel": channel,
                "destination": destination,
                "body": body,
                "purpose": purpose,
                "sent_at": utc_now().isoformat(),
            }
        )


def recent(limit: int = 20) -> List[Dict]:
    """The most recent messages, newest first."""
    with _lock:
        return list(_messages)[: max(1, limit)]


def clear() -> None:
    """Empty it. For tests, and for a developer starting a fresh walk-through."""
    with _lock:
        _messages.clear()
```

- [ ] **Step 4: Record from the fakes, and add the WhatsApp double**

**The recording happens in `messaging.py`, not in the providers.** A provider's
`send` receives no tenant id and no purpose — only a destination, a body or
template, and the school's configuration — so recording from inside a fake
would mean threading two parameters through both provider signatures for the
benefit of the test doubles alone. `messaging.py` already has both values in
hand, and it is already the one place that resolves, redacts and records.

In `messaging.py`, after the usage-recording block:

```python
    if resolved.client.is_test_double and result.success:
        from .outbox import record

        record(
            tenant_id=tenant_id,
            channel=channel,
            destination=destination,
            body=body or " | ".join(str(v) for v in (variables or [])),
            purpose=purpose,
        )
```

This keeps the fakes free of the outbox and puts the one `is_test_double` branch next to the one that already exists in the resolver. For WhatsApp, where there is no body, the variables are what a developer needs to read — the code is the first of them.

Add `FakeWhatsAppProvider` to `providers/fake.py`, mirroring `FakeSmsProvider` with `key = "fake_whatsapp"`, `name = "Fake WhatsApp (tests only)"`, the same `_FAILURES` behaviour map, and a `send` matching `WhatsAppProvider.send`.

Register both in `registry.py`:

```python
registry = ProviderRegistry([FakeSmsProvider(), FakeWhatsAppProvider()])
```

- [ ] **Step 5: Add the endpoint**

In `routes.py`, beside the other integration routes:

```python
@platform_bp.route("/integrations/outbox", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def read_integration_outbox():
    """GET /platform/integrations/outbox — what the test doubles pretended to send.

    **404 where test doubles may not run.** Not 403: an endpoint that exists
    and refuses tells an attacker it exists. The predicate is the resolver's,
    so "may a fake run here" has one answer rather than two.
    """
    from modules.integrations.outbox import recent
    from modules.integrations.resolver import _test_doubles_allowed

    if not _test_doubles_allowed():
        return not_found_response("Endpoint")

    return success_response(data={"messages": recent(limit=20)})
```

- [ ] **Step 6: Run the tests**

```bash
cd server && ./venv/bin/python -m pytest tests/test_integration_outbox.py tests/test_integrations_foundation.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd server && git add -A && git commit -m "$(cat <<'EOF'
feat(integrations): let a developer read what a fake provider sent

Without this the OTP flow cannot be walked at all: the code is valid for
five minutes and nothing can tell you what it is. In memory and bounded,
because an OTP in plaintext at rest is what the rest of auth refuses.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: The MSG91 adapter

**Files:**
- Create: `server/modules/integrations/providers/msg91.py`
- Modify: `server/modules/integrations/registry.py`
- Modify: `server/env.example`
- Test: `server/tests/test_provider_msg91.py` (create)

**Interfaces:**
- Consumes: `http.post_json`, `errors`, `credentials.resolve_secret`, `SmsProvider`
- Produces: `Msg91Provider` with `key = "msg91"`, `required_credentials = ("auth_key",)`, `supports_idempotency = False`

- [ ] **Step 1: Read the current vendor documentation**

Do not write this adapter from memory. Fetch MSG91's current Flow API reference and confirm: the endpoint, the auth header name, how a DLT template id is passed, how recipients and template variables are shaped, and what the error body looks like. Record the URL you used in the module docstring.

- [ ] **Step 2: Write the failing test**

Create `server/tests/test_provider_msg91.py`:

```python
"""The MSG91 client, against a mocked transport. Nothing here reaches a network."""

from unittest.mock import patch

from modules.integrations import errors
from modules.integrations.http import HttpResponse
from modules.integrations.providers.msg91 import Msg91Provider


def _ok(body='{"type":"success","message":"abc123"}'):
    return HttpResponse(200, body, {}), None


def test_the_dlt_template_id_is_sent(monkeypatch):
    monkeypatch.setenv("MSG91_AUTH_KEY", "test-key")
    captured = {}

    def fake_post(url, payload, headers=None, timeout=15):
        captured["payload"] = payload
        return _ok()

    with patch("modules.integrations.providers.msg91.post_json", fake_post):
        Msg91Provider().send(
            destination="+919876543210",
            body="418302 is your NexSchool sign-in code.",
            template_id="1707169900000000000",
            configuration={"sender_id": "NEXSCH"},
        )

    assert "1707169900000000000" in str(captured["payload"])


def test_a_missing_credential_is_a_configuration_error_not_a_crash(monkeypatch):
    monkeypatch.delenv("MSG91_AUTH_KEY", raising=False)
    result = Msg91Provider().send(
        destination="+919876543210", body="x", template_id="t",
        configuration={"sender_id": "NEXSCH"},
    )
    assert result.success is False
    assert result.error_code == errors.CONFIGURATION_ERROR


def test_a_rejected_credential_is_normalized(monkeypatch):
    monkeypatch.setenv("MSG91_AUTH_KEY", "wrong")
    with patch(
        "modules.integrations.providers.msg91.post_json",
        lambda *a, **k: (HttpResponse(401, '{"message":"unauthorized"}', {}), None),
    ):
        result = Msg91Provider().send(
            destination="+919876543210", body="x", template_id="t",
            configuration={"sender_id": "NEXSCH"},
        )
    assert result.error_code == errors.AUTHENTICATION_ERROR
    assert result.retryable is False


def test_a_timeout_is_not_retryable_because_the_message_may_have_gone(monkeypatch):
    monkeypatch.setenv("MSG91_AUTH_KEY", "test-key")
    with patch(
        "modules.integrations.providers.msg91.post_json",
        lambda *a, **k: (None, errors.TIMEOUT),
    ):
        result = Msg91Provider().send(
            destination="+919876543210", body="x", template_id="t",
            configuration={"sender_id": "NEXSCH"},
        )
    assert result.error_code == errors.TIMEOUT
    assert result.retryable is False


def test_health_sends_nothing(monkeypatch):
    monkeypatch.setenv("MSG91_AUTH_KEY", "test-key")
    with patch("modules.integrations.providers.msg91.post_json") as posted:
        report = Msg91Provider().health({"sender_id": "NEXSCH"})
    posted.assert_not_called()
    assert report.provider_reachable is None


def test_it_does_not_claim_delivery(monkeypatch):
    """MSG91 acknowledges a request. That is `accepted`, never `delivered`."""
    monkeypatch.setenv("MSG91_AUTH_KEY", "test-key")
    with patch("modules.integrations.providers.msg91.post_json", lambda *a, **k: _ok()):
        result = Msg91Provider().send(
            destination="+919876543210", body="x", template_id="t",
            configuration={"sender_id": "NEXSCH"},
        )
    assert result.status == "accepted"
```

- [ ] **Step 3: Run and watch it fail**

```bash
cd server && ./venv/bin/python -m pytest tests/test_provider_msg91.py -q
```

Expected: FAIL — module not found.

- [ ] **Step 4: Write the adapter**

Module docstring must state which documentation version it was written against, that `supports_idempotency` is `False` because MSG91's flow API takes no idempotency key — which is what stops `messaging.py` retrying a timeout and charging the school twice — and that `health()` reports configuration readiness only.

Structure: `_auth_key()` via `resolve_secret("MSG91_AUTH_KEY")`; a `configuration_error` result when it is absent; `post_json` to the flow endpoint with the auth header, the template id, the sender id from `configuration` and the destination; `_normalize(response)` mapping 401/403 → `AUTHENTICATION_ERROR`, 400/422 → `VALIDATION_ERROR`, 429 → `RATE_LIMITED`, 5xx → `PROVIDER_UNAVAILABLE`, anything else → `UNKNOWN_PROVIDER_ERROR`; success → `MessageSendResult(success=True, status=STATUS_ACCEPTED, provider_message_id=…, billable_units=1)`.

- [ ] **Step 5: Register it and document the variable**

Add `Msg91Provider()` to the registry list. Add to `env.example`:

```
# SMS provider (MSG91). The sender id and DLT template ids are not secrets
# and live on the school's integration row, not here.
MSG91_AUTH_KEY=
```

- [ ] **Step 6: Run the tests**

```bash
cd server && ./venv/bin/python -m pytest tests/test_provider_msg91.py tests/test_integrations_foundation.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd server && git add -A && git commit -m "$(cat <<'EOF'
feat(integrations): add the msg91 sms client

Registered but not usable until MSG91_AUTH_KEY is set, which the health
check already enforces. Declares no idempotency support, so a timed-out
send is never retried and a school is never charged twice.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: The Meta WhatsApp Cloud API adapter

**Files:**
- Create: `server/modules/integrations/providers/meta_whatsapp.py`
- Modify: `server/modules/integrations/registry.py`, `server/env.example`
- Test: `server/tests/test_provider_meta_whatsapp.py` (create)

**Interfaces:**
- Produces: `MetaWhatsAppProvider`, `key = "meta_whatsapp"`, `required_credentials = ("access_token",)`, `supports_idempotency = False`

- [ ] **Step 1: Read the current vendor documentation**

Confirm from Meta's current Cloud API reference: the messages endpoint and graph version, the bearer header, the `template` message body shape, how an **authentication-category** template's variables are supplied, and the error body shape. Record the URL in the docstring.

- [ ] **Step 2: Write the failing test**

Create `server/tests/test_provider_meta_whatsapp.py`, mirroring Task 8's file with these differences:

```python
def test_the_variables_are_sent_positionally(monkeypatch):
    """A template's slots are ordered by the template, not by us."""
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "test-token")
    captured = {}

    def fake_post(url, payload, headers=None, timeout=15):
        captured["payload"] = payload
        captured["url"] = url
        return HttpResponse(200, '{"messages":[{"id":"wamid.X"}]}', {}), None

    with patch("modules.integrations.providers.meta_whatsapp.post_json", fake_post):
        MetaWhatsAppProvider().send(
            destination="+919876543210",
            template_name="nexschool_login_code",
            variables=["418302", "5"],
            configuration={"phone_number_id": "123456", "language": "en"},
        )

    body = captured["payload"]
    assert body["type"] == "template"
    assert body["template"]["name"] == "nexschool_login_code"
    parameters = body["template"]["components"][0]["parameters"]
    assert [p["text"] for p in parameters] == ["418302", "5"]
    assert "123456" in captured["url"]


def test_a_missing_phone_number_id_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "test-token")
    result = MetaWhatsAppProvider().send(
        destination="+919876543210", template_name="t", variables=[],
        configuration={},
    )
    assert result.error_code == errors.CONFIGURATION_ERROR
```

Plus the same missing-credential, rejected-credential, timeout-not-retryable, health-sends-nothing and does-not-claim-delivery tests as Task 8.

- [ ] **Step 3: Run and watch it fail**

```bash
cd server && ./venv/bin/python -m pytest tests/test_provider_meta_whatsapp.py -q
```

Expected: FAIL — module not found.

- [ ] **Step 4: Write the adapter, register it, document the variables**

`env.example` gains:

```
# WhatsApp provider (Meta Cloud API). The phone number id and business
# account id are identifiers, not secrets, and live on the school's
# integration row.
META_WHATSAPP_ACCESS_TOKEN=
```

Note in the docstring that the token must be a **permanent system-user token**, not the 24-hour one the quickstart hands out, and that `provider_message_id` comes from `messages[0].id`.

- [ ] **Step 5: Run the tests and commit**

```bash
cd server && ./venv/bin/python -m pytest tests/test_provider_meta_whatsapp.py tests/test_integrations_foundation.py -q
cd server && git add -A && git commit -m "$(cat <<'EOF'
feat(integrations): add the meta whatsapp cloud api client

Sends only through an approved template, with variables positional
because the slot order belongs to the template and not to us.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Test send, and the disable guard

Two route-level behaviours, together because both are about an operator not being able to leave a school broken.

**Files:**
- Modify: `server/modules/platform/routes.py`
- Modify: `server/modules/integrations/services.py`
- Test: `server/tests/test_integration_test_send.py`, `server/tests/test_integration_lifecycle.py` (create)

**Interfaces:**
- Produces:
  - `POST /api/platform/tenants/<id>/integrations/<capability>/test-send`, body `{"destination": "+91…"}`
  - `services.methods_depending_on(tenant_id, capability) -> list[str]`
  - `set_integration_status` refuses `disabled` while a dependent method is enabled

- [ ] **Step 1: Write the failing tests**

`tests/test_integration_lifecycle.py`:

```python
"""An operator must not be able to leave a school half-broken."""

import pytest

from modules.integrations.services import IntegrationConfigurationError, set_integration_status


def test_disabling_a_depended_on_integration_is_refused(app, tenant, enabled_fake_sms, otp_enabled_for_students):
    """Otherwise the school keeps showing an OTP button whose codes will
    never arrive, with nothing anywhere saying so."""
    with pytest.raises(IntegrationConfigurationError) as raised:
        set_integration_status(tenant.id, capability="sms", status="disabled")
    assert "mobile_otp" in str(raised.value)


def test_disabling_is_allowed_once_the_method_is_off(app, tenant, enabled_fake_sms, otp_enabled_for_students):
    from core.database import db
    from modules.auth import policy

    policy.set_method(tenant.id, "student", "mobile_otp", enabled=False)
    db.session.commit()

    set_integration_status(tenant.id, capability="sms", status="disabled")


def test_a_channel_a_school_does_not_use_is_not_a_dependency(app, tenant, enabled_fake_sms, enabled_fake_whatsapp, otp_enabled_for_students):
    """The school is on SMS. Disabling its unused WhatsApp breaks nothing."""
    set_integration_status(tenant.id, capability="whatsapp", status="disabled")
```

`tests/test_integration_test_send.py`:

```python
def test_a_test_send_goes_through_the_template_path(app, tenant, platform_admin_client, enabled_fake_sms):
    """A test that bypassed templates would prove nothing about the case
    that actually fails."""
    from modules.integrations import outbox

    outbox.clear()
    response = platform_admin_client.post(
        f"/api/platform/tenants/{tenant.id}/integrations/sms/test-send",
        json={"destination": "+919876543210"},
    )
    assert response.status_code == 200
    assert outbox.recent()[0]["purpose"] == "integration_test"


def test_a_test_send_is_recorded_as_usage(app, tenant, platform_admin_client, enabled_fake_sms, sms_service_configured):
    from modules.billing.models import ServiceUsageRecord

    platform_admin_client.post(
        f"/api/platform/tenants/{tenant.id}/integrations/sms/test-send",
        json={"destination": "+919876543210"},
    )
    record = ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).first()
    assert record.usage_type == "integration_test"


def test_a_test_send_needs_a_platform_admin(app, tenant, tenant_admin_client, enabled_fake_sms):
    response = tenant_admin_client.post(
        f"/api/platform/tenants/{tenant.id}/integrations/sms/test-send",
        json={"destination": "+919876543210"},
    )
    assert response.status_code in (401, 403)


def test_a_test_send_is_bounded_per_actor(app, tenant, platform_admin_client, enabled_fake_sms, throttling):
    """Each press costs real money. Six in an hour is a mistake, not a test."""
    codes = [
        platform_admin_client.post(
            f"/api/platform/tenants/{tenant.id}/integrations/sms/test-send",
            json={"destination": "+919876543210"},
        ).status_code
        for _ in range(7)
    ]
    assert 429 in codes


def test_a_missing_destination_is_refused(app, tenant, platform_admin_client, enabled_fake_sms):
    response = platform_admin_client.post(
        f"/api/platform/tenants/{tenant.id}/integrations/sms/test-send", json={}
    )
    assert response.status_code == 400
```

Add a `PURPOSE_INTEGRATION_TEST = "integration_test"` constant to `templates.py` and a matching entry in each fixture's template map.

- [ ] **Step 2: Run and watch them fail**

```bash
cd server && ./venv/bin/python -m pytest tests/test_integration_lifecycle.py tests/test_integration_test_send.py -q
```

Expected: FAIL — no such route; `set_integration_status` disables without complaint.

- [ ] **Step 3: Add the dependency check**

In `services.py`:

```python
def methods_depending_on(tenant_id: str, capability: str) -> List[str]:
    """Which enabled sign-in methods would stop working without this.

    Derived rather than listed: a method is a dependant when it declares
    itself paid and the school's OTP channel is this capability. A future
    paid method is covered by declaring itself paid, not by somebody
    remembering to edit a list here.
    """
    from modules.auth import policy
    from modules.auth.strategies import registry as strategies

    if capability != policy.otp_delivery_channel(tenant_id):
        return []

    return sorted(
        key
        for key in strategies.keys()
        if getattr(strategies.get(key), "is_paid", False)
        and policy.is_method_enabled_anywhere(tenant_id, key)
    )
```

And in `set_integration_status`, before assigning a `disabled` status:

```python
    if status == STATUS_DISABLED:
        dependants = methods_depending_on(tenant_id, capability)
        if dependants:
            raise IntegrationConfigurationError(
                "This school signs people in with "
                + ", ".join(dependants)
                + f", which needs {capability}. Turn the method off first."
            )
```

- [ ] **Step 4: Add the test-send route**

```python
@platform_bp.route("/tenants/<tenant_id>/integrations/<capability>/test-send", methods=["POST"])
@limiter.limit("5 per hour", key_func=actor_rate_key)
@auth_required
@platform_admin_required
def test_send_integration(tenant_id, capability):
    """POST …/integrations/<capability>/test-send — send one real message.

    **Deliberately not folded into the health check.** `health.py` argues
    that proving an SMS integration works by sending an SMS charges the
    school and rings a real person's phone; a "test connection" button that
    quietly does that is a trap. So health stays free and silent, and this is
    a separate action whose screen says what it costs.

    It goes through the same template path as a real send. A test that
    bypassed templates would prove nothing about the case that actually
    fails, which is a template that was never registered.
    """
    from core.models import Tenant
    from modules.integrations.messaging import send_message
    from modules.integrations.templates import PURPOSE_INTEGRATION_TEST

    if not Tenant.query.get(tenant_id):
        return not_found_response("Tenant")

    data = request.get_json(silent=True) or {}
    destination = (data.get("destination") or "").strip()
    if not destination:
        return validation_error_response(
            {"destination": "A number to send the test message to is required."}
        )

    result = send_message(
        tenant_id=tenant_id,
        channel=capability,
        purpose=PURPOSE_INTEGRATION_TEST,
        destination=destination,
        variables=["test"],
        body="This is a NexSchool test message. No action is needed.",
    )
    db.session.commit()

    return success_response(
        data={
            "sent": result.success,
            "status": result.status,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "operation_id": result.operation_id,
        }
    )
```

Import `actor_rate_key` from `core.extensions`.

- [ ] **Step 5: Run the tests**

```bash
cd server && ./venv/bin/python -m pytest tests/test_integration_lifecycle.py tests/test_integration_test_send.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the whole server suite**

```bash
cd server && ./venv/bin/python -m pytest -q 2>&1 | tail -5
```

Expected: no new failures against the baseline in Global Constraints.

- [ ] **Step 7: Commit**

```bash
cd server && git add -A && git commit -m "$(cat <<'EOF'
feat(integrations): a test send, and a guard on turning one off

Disabling an integration a sign-in method depends on is now refused and
names the method. It was possible to switch off a school's SMS and leave
it showing an OTP button whose codes would never arrive.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Server documentation

**Files:**
- Modify: `server/docs/modules/integrations.md`, `server/docs/modules/mobile-otp-authentication.md`
- Modify: `server/docs/architecture/identity-domain.md`, `server/docs/architecture/debt-register.md`
- Create: `server/docs/architecture/adr/ADR-015-one-otp-channel-no-fallback.md`

- [ ] **Step 1: Write the ADR**

Record: the decision (one channel per school, no automatic fallback), the context (two channels now exist and fallback is the obvious next thought), the consequences (a channel outage is an outage; the alternative doubles failure modes and makes a bill hard to explain), and the trigger that would reopen it (measured delivery failure on one channel).

- [ ] **Step 2: Update the module docs with minimal diffs**

`integrations.md` gains the WhatsApp capability, the template concept, the outbox and the test-send route. `mobile-otp-authentication.md` gains the channel choice. No rewrites, no cosmetics.

- [ ] **Step 3: Register the debt**

Add to the debt register, open: **the `whatsapp` billing service must exist in the catalog** before WhatsApp usage can be recorded — `usage_recorder` calls `record_usage(service_key=capability)`, and an unknown service is logged and dropped, not raised. Until a `whatsapp` service is added via `POST /platform/service-catalog/services`, WhatsApp messages send but do not bill.

- [ ] **Step 4: Commit**

```bash
cd server && git add -A && git commit -m "$(cat <<'EOF'
docs(integrations): record the second channel and the no-fallback decision

Registers the open debt that whatsapp usage is dropped rather than billed
until a whatsapp service exists in the catalog.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Panel test harness

The panel has **no test framework at all** — `package.json` has `dev`, `build`, `start`, `lint` and nothing else. admin-web has vitest 4, Testing Library and jsdom; copy that setup rather than inventing a second one.

**Files:**
- Modify: `panel/package.json`
- Create: `panel/vitest.config.ts`, `panel/vitest.setup.ts`
- Create: `panel/lib/api.test.ts` (a smoke test proving the harness runs)

- [ ] **Step 1: Copy the dependency set from admin-web**

```bash
cd panel && npm install -D vitest@^4.1.5 @vitejs/plugin-react jsdom@^27.0.1 \
  @testing-library/react@^16.3.2 @testing-library/jest-dom@^6.9.1 \
  @testing-library/user-event@^14.6.1
```

- [ ] **Step 2: Add the scripts**

In `panel/package.json`:

```json
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit"
```

- [ ] **Step 3: Add the config**

`panel/vitest.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, ".") } },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
  },
});
```

`panel/vitest.setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 4: Write a smoke test**

`panel/lib/api.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { getErrorMessage } from "./api";

describe("getErrorMessage", () => {
  it("returns a readable message for an unknown value", () => {
    expect(typeof getErrorMessage(null)).toBe("string");
  });
});
```

- [ ] **Step 5: Run it**

```bash
cd panel && npm test
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
cd panel && git add -A && git commit -m "$(cat <<'EOF'
chore(panel): add a test harness

The panel had none. Mirrors admin-web's vitest and testing-library setup
rather than introducing a second way of testing a Next app in one repo.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Login & access becomes writable

The task that unblocks testing `admission_id_password` and `mobile_pin`, neither of which needs a provider at all.

**Files:**
- Modify: `panel/types/index.ts`, `panel/hooks/useApi.ts`
- Modify: `panel/app/(dashboard)/dashboard/tenants/[id]/login-access-section.tsx`
- Test: `panel/app/(dashboard)/dashboard/tenants/[id]/login-access-section.test.tsx` (create)

**Interfaces:**
- Consumes: `PATCH /api/platform/tenants/<id>/auth-policy`, `PATCH …/auth-policy/methods`
- Produces:
  - `TenantAuthPolicy` gains `otpDeliveryChannel: string`
  - `useSetAuthMethod(tenantId)` — mutation `{ methodKey, subjectKind, enabled, surface? }`
  - `useUpdateAuthPolicy(tenantId)` — mutation `{ familyAccessMode?, studentCredentialPolicy?, otpDeliveryChannel? }`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

// Mock the hooks module so the component is tested, not the network.
const setMethod = vi.fn();
vi.mock("@/hooks/useApi", () => ({
  useTenantAuthPolicy: () => ({
    data: {
      tenantId: "t1",
      familyAccessMode: "shared_with_student",
      studentCredentialPolicy: "force_change_on_first_login",
      otpDeliveryChannel: "sms",
      isConfigured: true,
      updatedAt: null,
      rules: [
        { subjectKind: "student", surface: "any", methodKey: "email_password", isEnabled: true, enabledAt: null, notes: null },
        { subjectKind: "student", surface: "any", methodKey: "mobile_otp", isEnabled: false, enabledAt: null, notes: null },
      ],
    },
    isLoading: false,
    error: null,
  }),
  useSetAuthMethod: () => ({ mutateAsync: setMethod, isPending: false }),
  useUpdateAuthPolicy: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useTenantIntegrations: () => ({ data: [], isLoading: false }),
}));

describe("LoginAccessSection", () => {
  it("no longer claims the policy does not control sign-in", async () => {
    const { LoginAccessSection } = await import("./login-access-section");
    render(<LoginAccessSection tenantId="t1" />);
    expect(screen.queryByText(/does not yet control who may sign in/i)).toBeNull();
  });

  it("switches a method on through the policy endpoint", async () => {
    const { LoginAccessSection } = await import("./login-access-section");
    render(<LoginAccessSection tenantId="t1" />);
    await userEvent.click(screen.getByRole("switch", { name: /admission number|mobile number \+ PIN|email/i }));
    expect(setMethod).toHaveBeenCalled();
  });

  it("warns when a method needs a channel the school has not got", async () => {
    const { LoginAccessSection } = await import("./login-access-section");
    render(<LoginAccessSection tenantId="t1" />);
    expect(screen.getByText(/no working sms provider|configure/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run and watch it fail**

```bash
cd panel && npm test -- login-access-section
```

Expected: FAIL — the hooks do not exist.

- [ ] **Step 3: Add the mutations**

In `hooks/useApi.ts`, replacing the "Read-only: there is no mutation endpoint for it yet" comment on `useTenantAuthPolicy` (it is now false) and adding `otpDeliveryChannel` to the mapped object:

```ts
/** Turn one sign-in method on or off for one kind of person. */
export function useSetAuthMethod(tenantId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      methodKey: string;
      subjectKind: string;
      enabled: boolean;
      surface?: string;
    }) =>
      api.patch(`/api/platform/tenants/${tenantId}/auth-policy/methods`, {
        method_key: input.methodKey,
        subject_kind: input.subjectKind,
        enabled: input.enabled,
        surface: input.surface ?? "any",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TENANT_AUTH_POLICY_KEY(tenantId) });
    },
  });
}

/** The settings that are not methods: family access, the credential policy,
 *  and which wire carries a sign-in code. */
export function useUpdateAuthPolicy(tenantId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      familyAccessMode?: string;
      studentCredentialPolicy?: string;
      otpDeliveryChannel?: string;
    }) =>
      api.patch(`/api/platform/tenants/${tenantId}/auth-policy`, {
        family_access_mode: input.familyAccessMode,
        student_credential_policy: input.studentCredentialPolicy,
        otp_delivery_channel: input.otpDeliveryChannel,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: TENANT_AUTH_POLICY_KEY(tenantId) });
    },
  });
}
```

- [ ] **Step 4: Make the section writable**

Replace each `<Badge>` with a shadcn `<Switch>` calling `useSetAuthMethod`. Add `<Select>` controls for family access mode, student credential policy, and — shown only when `mobile_otp` is enabled for any subject — OTP delivery channel.

Add the readiness banner above the grid: when a rule for a paid method is enabled (or is being enabled) and `useTenantIntegrations` reports no ready integration for the school's channel, render a warning naming the channel with a link to the Integrations section.

Server errors must be surfaced verbatim, not swallowed: the API refuses an impossible change with a message that says exactly what is missing, and that message is more useful than anything the screen could invent.

**Delete the final paragraph** — *"Read-only. Sign-in still uses email and password for everyone; this policy is recorded for the authentication work in progress and does not yet control who may sign in."* It has been false since Phase 8. Update the component's docstring, which says the same thing.

- [ ] **Step 5: Run the tests and the type check**

```bash
cd panel && npm test && npx tsc --noEmit
```

Expected: PASS, clean.

- [ ] **Step 6: Commit**

```bash
cd panel && git add -A && git commit -m "$(cat <<'EOF'
feat(panel): let an operator change a school's sign-in methods

The card said the policy does not control who may sign in. Phase 8 made
that false, and the sentence was still shipping.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: The tenant Integrations section

**Files:**
- Create: `panel/app/(dashboard)/dashboard/tenants/[id]/integrations-section.tsx`
- Modify: `panel/app/(dashboard)/dashboard/tenants/[id]/tenant-detail-view.tsx`, `panel/hooks/useApi.ts`, `panel/types/index.ts`
- Test: `panel/app/(dashboard)/dashboard/tenants/[id]/integrations-section.test.tsx` (create)

**Interfaces:**
- Produces: `useTenantIntegrations(tenantId)`, `useConfigureIntegration(tenantId)`, `useSetIntegrationStatus(tenantId)`, `useTestSend(tenantId)`, `useIntegrationOutbox()`, and types `TenantIntegration`, `IntegrationHealth`, `IntegrationCapability`

- [ ] **Step 1: Write the failing test**

Cover, with the hooks mocked: health is rendered; the credential field is labelled as taking a variable **name** and rejects a pasted-looking value before submitting; the test-send control states that it sends a real billable message and asks for confirmation; the outbox card is absent when `useIntegrationOutbox` reports unavailable.

- [ ] **Step 2: Run and watch it fail**

```bash
cd panel && npm test -- integrations-section
```

- [ ] **Step 3: Add the hooks and types, then the component**

The configuration form has two visually distinct halves, per spec §10.2:

- **Settings** — sender id, template ids, phone number id. Non-secret, freely displayed.
- **Credentials** — environment variable **names** only, each showing whether it currently resolves on this server. Client-side, refuse a value that does not match `/^[A-Z][A-Z0-9_]{2,63}$/` with the reason, so the operator is told before the server has to.

- [ ] **Step 4: Mount it in `tenant-detail-view.tsx`**

Directly below `<LoginAccessSection tenantId={id} />` at line 596, so the readiness banner's link has a target on the same page.

- [ ] **Step 5: Run the tests, type check, commit**

```bash
cd panel && npm test && npx tsc --noEmit
cd panel && git add -A && git commit -m "$(cat <<'EOF'
feat(panel): configure a school's messaging providers

Credentials are collected as environment variable names and never as
values, which is what the server has always enforced and what no screen
previously said.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: The integrations catalog page

**Files:**
- Create: `panel/app/(dashboard)/dashboard/integrations/page.tsx`
- Modify: `panel/components/layout/sidebar.tsx`, `panel/hooks/useApi.ts`
- Test: `panel/app/(dashboard)/dashboard/integrations/page.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /api/platform/integration-capabilities`
- Produces: `useIntegrationCapabilities()`

- [ ] **Step 1: Write the failing test**

Assert that each capability is listed with its providers; that a provider whose `is_test_double` is true is labelled as a test double; and that no credential **value** appears anywhere — only names and a set/not-set indicator.

- [ ] **Step 2: Run and watch it fail**

```bash
cd panel && npm test -- integrations/page
```

- [ ] **Step 3: Build the page and add the nav entry**

The page answers "can we offer WhatsApp at all yet?" without opening a school: capabilities, their registered providers, and whether each provider's credentials are present on this server. No tenant appears on it, because none of it is per-school.

In `sidebar.tsx`, after the Tenants entry:

```tsx
  { href: "/dashboard/integrations", label: "Integrations", icon: Plug },
```

- [ ] **Step 4: Run everything and commit**

```bash
cd panel && npm test && npx tsc --noEmit && npm run lint
cd panel && git add -A && git commit -m "$(cat <<'EOF'
feat(panel): show what this build can send and who could send it

Read from the provider registry, so it describes the deployed code
rather than anybody's configuration.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Walk it as an operator and a student

Tests passing is not the same as the feature working. Required by `.claude/rules/team-workflow.md` stage 5.

- [ ] **Step 1: Bring the stack up and confirm `DEBUG` is on**

Test doubles resolve only under `TESTING` or `DEBUG`; without one the fake providers are refused and none of this walk-through works.

- [ ] **Step 2: As a platform admin, walk the configuration**

Configure a school onto `fake_sms` with a `login_otp` template, enable it, read the health report, switch on Mobile + OTP for students, and press Send test message. Confirm the test message appears in the outbox and on the school's usage.

- [ ] **Step 3: As a student, sign in with a code**

Request an OTP from admin-web, read the code from the outbox card, complete the sign-in, and confirm a session exists on the student's Sign-in tab.

- [ ] **Step 4: Walk the two methods that need no provider**

Sign in with an admission number and password, and with a mobile number and PIN. These are the two the operator could never previously switch on.

- [ ] **Step 5: Walk the refusals**

Try to disable the SMS integration while OTP is on — expect a refusal naming the method. Try to enable OTP at a school with no provider — expect a refusal naming what is missing. Move a school to WhatsApp with no WhatsApp provider while OTP is on — expect a refusal.

- [ ] **Step 6: Confirm the outbox is absent in production mode**

Set `DEBUG=0` and `TESTING=0`, restart, and confirm `GET /api/platform/integrations/outbox` returns 404 and the panel card is gone.

- [ ] **Step 7: Record what the walk found**

Write `server/AUTHENTICATION_PHASE_9_RESULTS.md` in the style of the Phase 8 report: what was wrong, what it is now, what was deliberately not done, and the registration checklist from spec §14 as the remaining critical path. Fix anything the walk surfaced before writing that it passed.

- [ ] **Step 8: Final verification across all repos**

```bash
cd server && ./venv/bin/python -m pytest -q 2>&1 | tail -3
cd panel && npm test && npx tsc --noEmit && npm run lint
cd admin-web && npx tsc --noEmit
```

- [ ] **Step 9: Commit**

```bash
cd server && git add -A && git commit -m "$(cat <<'EOF'
docs(auth): phase 9 results

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

**Spec coverage.** §3 templates → Task 3. §4 capability layer → Tasks 1, 2, 4. §5 channel → Tasks 5, 6. §6 providers → Tasks 7, 8, 9. §7 outbox → Task 7. §8 test send → Task 10. §9 lifecycle → Task 10. §10 panel → Tasks 12–15. §11 migration → Task 5. §12 tests → throughout. §14 registration checklist → Task 16 step 7. §15 sequence → task order.

**One deviation from the spec, deliberately.** Spec §7 has the fake providers write to the outbox themselves. Task 7 records from `messaging.py` instead, guarded on `is_test_double`, because the providers do not receive the tenant id and threading it through their signatures would exist only for the fakes. The `is_test_double` branch then sits beside the one already in the resolver rather than being spread across every double.

**One addition the spec did not anticipate.** Task 12: the panel has no test framework. Spec §12 asks for panel component tests without noting there is nothing to run them.

**One open item recorded as debt rather than built.** WhatsApp usage will not bill until a `whatsapp` service exists in the billing catalog — `usage_recorder` logs and drops an unknown service rather than raising. Task 11 registers it; it is a catalog entry an operator makes, not code.
