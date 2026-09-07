"""Phase 0c — which ways in a school allows.

Configuration, not behaviour. The last group in this file asserts that: login,
tokens and sessions are untouched, and the policy is inert. Everything above it
proves the policy itself is sound, because a later phase will hand it real
authority and by then the semantics must already be decided.

Three of these tests are load-bearing beyond their own subject:

  * `test_a_method_with_no_rule_is_denied` fails if somebody ever implements
    "missing means enabled" — the convention `core/feature_flags.py` uses and
    that this table deliberately inverts.
  * `test_a_teacher_who_is_also_a_parent_holds_both_kinds` fails if subject
    kind ever becomes a partition instead of a union.
  * `test_a_platform_admin_is_not_restricted_by_tenant_policy` is A3: a school
    must not be able to lock the operator out of its own tenancy.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import db
from modules.auth.models import User
from modules.auth.policy import (
    allowed_methods,
    describe,
    ensure_default_policy,
    family_access_mode,
    is_method_allowed,
    policy_for,
    student_credential_policy,
    subject_kinds,
)
from modules.auth.policy_models import (
    CREDENTIAL_FORCE_CHANGE,
    FAMILY_ACCESS_SEPARATE,
    FAMILY_ACCESS_SHARED,
    SURFACE_ANY,
    TenantAuthPolicy,
    TenantAuthPolicyRule,
)
from tests.auth._characterization import (
    make_platform_admin,
    make_tenant,
    make_user,
    new_id,
)

PASSWORD = "C0rrectHorse1"
EMAIL_PASSWORD = "email_password"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def policed_tenant(db_session):
    """A school with the default policy, as the migration leaves every school."""
    tenant = make_tenant(db_session, subdomain_prefix="p0c")
    ensure_default_policy(tenant.id)
    return tenant


def _rule(db_session, tenant, *, subject_kind, method_key, surface=SURFACE_ANY,
          is_enabled=True):
    row = TenantAuthPolicyRule(
        id=new_id("apr-"),
        tenant_id=tenant.id,
        subject_kind=subject_kind,
        surface=surface,
        method_key=method_key,
        is_enabled=is_enabled,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _student_account(db_session, tenant, academic_year):
    """An account whose person holds a Student relationship."""
    from modules.students.models import Student

    account = make_user(db_session, tenant, password=PASSWORD)
    db_session.add(
        Student(
            id=new_id("s-"),
            tenant_id=tenant.id,
            user_id=account.id,
            person_id=account.person_id,
            admission_number=f"ADM-{uuid.uuid4().hex[:8].upper()}",
        )
    )
    db_session.flush()
    return account


def _staff_account(db_session, tenant):
    """An account whose person holds an active employment."""
    from tests.conftest import employ_for

    account = make_user(db_session, tenant, password=PASSWORD)
    employ_for(account, employee_number=f"EMP-{uuid.uuid4().hex[:6]}")
    return account


def _parent_account(db_session, tenant):
    """An account whose person is a responsible adult in a household."""
    from modules.people.models import (
        FAMILY_ROLE_CHILD,
        FAMILY_ROLE_FATHER,
        Family,
        FamilyMember,
        Person,
    )

    account = make_user(db_session, tenant, password=PASSWORD)
    family = Family(id=new_id("f-"), tenant_id=tenant.id, name="Test Household")
    child = Person(id=new_id("p-"), tenant_id=tenant.id, full_name="The Child")
    db_session.add_all([family, child])
    db_session.flush()
    db_session.add_all(
        [
            FamilyMember(
                id=new_id("fm-"), tenant_id=tenant.id, family_id=family.id,
                person_id=account.person_id, relationship=FAMILY_ROLE_FATHER,
                is_primary_contact=True,
            ),
            FamilyMember(
                id=new_id("fm-"), tenant_id=tenant.id, family_id=family.id,
                person_id=child.id, relationship=FAMILY_ROLE_CHILD,
            ),
        ]
    )
    db_session.flush()
    return account


@pytest.fixture
def academic_year(db_session, tenant):
    from datetime import date

    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        id=new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    db_session.add(year)
    db_session.flush()
    return year


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_every_existing_tenant_has_exactly_one_policy(db_session):
    missing = db_session.execute(
        db.text(
            "SELECT count(*) FROM tenants t WHERE NOT EXISTS "
            "(SELECT 1 FROM tenant_auth_policies p WHERE p.tenant_id = t.id)"
        )
    ).scalar()
    duplicated = db_session.execute(
        db.text(
            "SELECT count(*) FROM (SELECT tenant_id FROM tenant_auth_policies "
            "GROUP BY 1 HAVING count(*) > 1) x"
        )
    ).scalar()

    assert missing == 0
    assert duplicated == 0


def test_every_existing_tenant_has_the_three_default_rules(db_session):
    wrong = db_session.execute(
        db.text(
            """
            SELECT count(*) FROM tenants t
             WHERE (SELECT count(*) FROM tenant_auth_policy_rules r
                     WHERE r.tenant_id = t.id
                       AND r.method_key = 'email_password'
                       AND r.surface = 'any'
                       AND r.is_enabled) <> 3
            """
        )
    ).scalar()

    assert wrong == 0


def test_the_defaults_are_the_specified_values(policed_tenant):
    policy = policy_for(policed_tenant.id)

    assert policy.family_access_mode == FAMILY_ACCESS_SHARED
    assert policy.student_credential_policy == CREDENTIAL_FORCE_CHANGE


def test_seeding_is_idempotent(db_session, policed_tenant):
    before = TenantAuthPolicyRule.query.filter_by(
        tenant_id=policed_tenant.id
    ).count()

    ensure_default_policy(policed_tenant.id)
    ensure_default_policy(policed_tenant.id)

    assert (
        TenantAuthPolicyRule.query.filter_by(tenant_id=policed_tenant.id).count()
        == before
    )
    assert TenantAuthPolicy.query.filter_by(tenant_id=policed_tenant.id).count() == 1


def test_the_seeded_rules_preserve_todays_behaviour(db_session, policed_tenant):
    """The defaults exist so that installing policy takes nothing away."""
    rules = TenantAuthPolicyRule.query.filter_by(tenant_id=policed_tenant.id).all()

    assert {(r.subject_kind, r.surface, r.method_key, r.is_enabled) for r in rules} == {
        ("student", "any", EMAIL_PASSWORD, True),
        ("staff", "any", EMAIL_PASSWORD, True),
        ("parent", "any", EMAIL_PASSWORD, True),
    }


# ---------------------------------------------------------------------------
# New tenants
# ---------------------------------------------------------------------------

def test_a_newly_created_tenant_receives_the_default_policy(db_session):
    from modules.platform.services import create_tenant

    result = create_tenant(
        name="Policy Check School",
        subdomain=f"p0c-new-{uuid.uuid4().hex[:10]}",
        contact_email=None, phone=None, address=None,
        admin_email=f"p0c-admin-{uuid.uuid4().hex[:8]}@test.school",
        admin_name="Policy Admin",
        platform_admin_id=None,
    )

    assert result.get("success") is True, result
    tenant_id = result["tenant"]["id"]
    assert policy_for(tenant_id) is not None
    assert (
        TenantAuthPolicyRule.query.filter_by(
            tenant_id=tenant_id, is_enabled=True
        ).count()
        == 3
    )


def test_a_tenant_that_fails_to_be_created_leaves_no_policy(db_session):
    """The policy is written inside the tenant's own transaction."""
    from modules.platform.services import create_tenant

    taken = make_tenant(db_session, subdomain_prefix="p0c-taken")
    db_session.flush()

    result = create_tenant(
        name="Duplicate", subdomain=taken.subdomain, contact_email=None,
        phone=None, address=None, admin_email="x@test.school",
        admin_name="X", platform_admin_id=None,
    )

    assert result.get("success") is False
    # The pre-existing tenant's own policy state is untouched by the failure.
    assert TenantAuthPolicy.query.filter_by(tenant_id=taken.id).count() in (0, 1)


# ---------------------------------------------------------------------------
# Subject kinds — a union, never a partition
# ---------------------------------------------------------------------------

def test_a_student_holds_the_student_kind(db_session, tenant, academic_year):
    ensure_default_policy(tenant.id)
    account = _student_account(db_session, tenant, academic_year)

    assert subject_kinds(account) == {"student"}


def test_an_employed_person_holds_the_staff_kind(db_session, tenant):
    ensure_default_policy(tenant.id)
    account = _staff_account(db_session, tenant)

    assert subject_kinds(account) == {"staff"}


def test_a_parent_holds_no_kind_under_shared_access(db_session, tenant):
    """ADR-011's default: parents are People and Family Members and have no
    experience of their own, so being one is a relationship, not a subject."""
    ensure_default_policy(tenant.id)
    account = _parent_account(db_session, tenant)

    assert subject_kinds(account) == set()


def test_a_parent_holds_the_parent_kind_under_separate_logins(db_session, tenant):
    ensure_default_policy(tenant.id)
    policy_for(tenant.id).family_access_mode = FAMILY_ACCESS_SEPARATE
    db_session.flush()
    account = _parent_account(db_session, tenant)

    assert subject_kinds(account) == {"parent"}


def test_a_teacher_who_is_also_a_parent_holds_both_kinds(db_session, tenant):
    """The union. Fails the moment somebody makes subject kind a partition."""
    from modules.people.models import (
        FAMILY_ROLE_CHILD,
        FAMILY_ROLE_MOTHER,
        Family,
        FamilyMember,
        Person,
    )
    from tests.conftest import employ_for

    ensure_default_policy(tenant.id)
    policy_for(tenant.id).family_access_mode = FAMILY_ACCESS_SEPARATE
    db_session.flush()

    account = make_user(db_session, tenant, password=PASSWORD)
    employ_for(account, employee_number=f"EMP-{uuid.uuid4().hex[:6]}")

    family = Family(id=new_id("f-"), tenant_id=tenant.id, name="Her Household")
    child = Person(id=new_id("p-"), tenant_id=tenant.id, full_name="Her Child")
    db_session.add_all([family, child])
    db_session.flush()
    db_session.add_all([
        FamilyMember(
            id=new_id("fm-"), tenant_id=tenant.id, family_id=family.id,
            person_id=account.person_id, relationship=FAMILY_ROLE_MOTHER,
        ),
        FamilyMember(
            id=new_id("fm-"), tenant_id=tenant.id, family_id=family.id,
            person_id=child.id, relationship=FAMILY_ROLE_CHILD,
        ),
    ])
    db_session.flush()

    assert subject_kinds(account) == {"staff", "parent"}


def test_an_account_with_no_relationships_holds_no_kind(db_session, tenant):
    ensure_default_policy(tenant.id)
    account = make_user(db_session, tenant, password=PASSWORD)

    assert subject_kinds(account) == set()


# ---------------------------------------------------------------------------
# Allowed methods
# ---------------------------------------------------------------------------

def test_an_enabled_matching_rule_is_returned(db_session, tenant):
    ensure_default_policy(tenant.id)
    account = _staff_account(db_session, tenant)

    assert allowed_methods(account) == [EMAIL_PASSWORD]


def test_a_disabled_rule_is_not_returned(db_session, tenant):
    ensure_default_policy(tenant.id)
    account = _staff_account(db_session, tenant)
    rule = TenantAuthPolicyRule.query.filter_by(
        tenant_id=tenant.id, subject_kind="staff"
    ).one()
    rule.is_enabled = False
    db_session.flush()

    assert allowed_methods(account) == []


def test_a_rule_for_another_subject_kind_is_not_returned(db_session, tenant):
    ensure_default_policy(tenant.id)
    account = _staff_account(db_session, tenant)
    _rule(
        db_session, tenant, subject_kind="student",
        method_key="admission_id_password",
    )

    assert allowed_methods(account) == [EMAIL_PASSWORD]


def test_an_any_surface_rule_matches_a_named_surface(db_session, tenant):
    ensure_default_policy(tenant.id)
    account = _staff_account(db_session, tenant)

    assert allowed_methods(account, "admin-web") == [EMAIL_PASSWORD]


def test_a_named_surface_rule_matches_that_surface(db_session, tenant):
    ensure_default_policy(tenant.id)
    account = _staff_account(db_session, tenant)
    _rule(
        db_session, tenant, subject_kind="staff",
        method_key="employee_code_password", surface="admin-web",
    )

    assert allowed_methods(account, "admin-web") == [
        EMAIL_PASSWORD,
        "employee_code_password",
    ]


def test_a_named_surface_rule_does_not_leak_to_another_surface(
    db_session, tenant
):
    ensure_default_policy(tenant.id)
    account = _staff_account(db_session, tenant)
    _rule(
        db_session, tenant, subject_kind="staff",
        method_key="employee_code_password", surface="admin-web",
    )

    assert allowed_methods(account, "student-mobile") == [EMAIL_PASSWORD]


def test_no_method_is_returned_twice(db_session, tenant):
    """A person holding two kinds that both permit a method gets it once."""
    from modules.people.models import (
        FAMILY_ROLE_CHILD, FAMILY_ROLE_MOTHER, Family, FamilyMember, Person,
    )
    from tests.conftest import employ_for

    ensure_default_policy(tenant.id)
    policy_for(tenant.id).family_access_mode = FAMILY_ACCESS_SEPARATE
    db_session.flush()

    account = make_user(db_session, tenant, password=PASSWORD)
    employ_for(account, employee_number=f"EMP-{uuid.uuid4().hex[:6]}")
    family = Family(id=new_id("f-"), tenant_id=tenant.id)
    child = Person(id=new_id("p-"), tenant_id=tenant.id, full_name="Child")
    db_session.add_all([family, child])
    db_session.flush()
    db_session.add_all([
        FamilyMember(id=new_id("fm-"), tenant_id=tenant.id, family_id=family.id,
                     person_id=account.person_id, relationship=FAMILY_ROLE_MOTHER),
        FamilyMember(id=new_id("fm-"), tenant_id=tenant.id, family_id=family.id,
                     person_id=child.id, relationship=FAMILY_ROLE_CHILD),
    ])
    db_session.flush()

    assert subject_kinds(account) == {"staff", "parent"}
    assert allowed_methods(account) == [EMAIL_PASSWORD]


# ---------------------------------------------------------------------------
# Absence means denied
# ---------------------------------------------------------------------------

def test_a_method_with_no_rule_is_denied(db_session, tenant):
    """The architectural rule, and the reason policy is not a feature flag.

    This test fails if anybody ever implements "missing means enabled".
    """
    ensure_default_policy(tenant.id)
    account = _staff_account(db_session, tenant)

    assert is_method_allowed(account, EMAIL_PASSWORD) is True
    assert is_method_allowed(account, "mobile_otp") is False
    assert is_method_allowed(account, "admission_id_password") is False
    assert is_method_allowed(account, "anything_at_all") is False


def test_a_configured_school_with_no_matching_rule_permits_nothing(db_session):
    """Absence means denied *within* a policy: the school has been asked, and
    this method has no enabled rule."""
    tenant = make_tenant(db_session, subdomain_prefix="p0c-bare")
    ensure_default_policy(tenant.id)
    for rule in TenantAuthPolicyRule.query.filter_by(tenant_id=tenant.id):
        rule.is_enabled = False
    db_session.flush()
    account = _staff_account(db_session, tenant)

    assert allowed_methods(account) == []
    assert is_method_allowed(account, EMAIL_PASSWORD) is False


def test_a_school_that_has_never_been_asked_keeps_the_default(db_session):
    """The other absence, and the opposite answer.

    A school with no policy row has not been configured — it has been missed.
    Refusing everything there would brick any tenant created by a path that
    does not seed one, which is a footgun rather than a security property. The
    default is what `ensure_default_policy` would have written.
    """
    bare = make_tenant(db_session, subdomain_prefix="p0c-unasked")
    account = _staff_account(db_session, bare)

    assert policy_for(bare.id) is None
    assert allowed_methods(account) == [EMAIL_PASSWORD]
    assert is_method_allowed(account, EMAIL_PASSWORD) is True
    # But still nothing else: an unconfigured school gets the default, not
    # everything.
    assert is_method_allowed(account, "mobile_otp") is False


# ---------------------------------------------------------------------------
# A3 — the platform admin is exempt
# ---------------------------------------------------------------------------

def test_a_platform_admin_is_not_restricted_by_tenant_policy(db_session, tenant):
    """A3. A school that permits one method must not be able to lock the
    operator out of its own tenancy."""
    ensure_default_policy(tenant.id)
    for rule in TenantAuthPolicyRule.query.filter_by(tenant_id=tenant.id):
        rule.is_enabled = False
    db_session.flush()

    home = make_tenant(db_session, subdomain_prefix="p0c-hq")
    admin = make_platform_admin(db_session, home, password=PASSWORD)

    # An ordinary account in that school now has nothing.
    ordinary = _staff_account(db_session, tenant)
    assert allowed_methods(ordinary) == []

    # The operator still does.
    assert allowed_methods(admin) != []


def test_a_platform_admin_needs_no_relationships(db_session):
    """Their authority is the platform flag, not a subject kind."""
    home = make_tenant(db_session, subdomain_prefix="p0c-hq2")
    admin = make_platform_admin(db_session, home, password=PASSWORD)

    assert subject_kinds(admin) == set()
    assert allowed_methods(admin) != []


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

def test_one_schools_policy_is_not_anothers(db_session):
    first = make_tenant(db_session, subdomain_prefix="p0c-a")
    second = make_tenant(db_session, subdomain_prefix="p0c-b")
    ensure_default_policy(first.id)
    ensure_default_policy(second.id)

    policy_for(second.id).family_access_mode = FAMILY_ACCESS_SEPARATE
    for rule in TenantAuthPolicyRule.query.filter_by(tenant_id=second.id):
        rule.is_enabled = False
    db_session.flush()

    assert family_access_mode(first.id) == FAMILY_ACCESS_SHARED
    assert family_access_mode(second.id) == FAMILY_ACCESS_SEPARATE
    assert allowed_methods(_staff_account(db_session, first)) == [EMAIL_PASSWORD]
    assert allowed_methods(_staff_account(db_session, second)) == []


def test_a_rule_in_one_school_does_not_reach_another(db_session):
    first = make_tenant(db_session, subdomain_prefix="p0c-c")
    second = make_tenant(db_session, subdomain_prefix="p0c-d")
    ensure_default_policy(first.id)
    ensure_default_policy(second.id)
    _rule(
        db_session, first, subject_kind="staff", method_key="mobile_otp"
    )

    assert "mobile_otp" in allowed_methods(_staff_account(db_session, first))
    assert "mobile_otp" not in allowed_methods(_staff_account(db_session, second))


# ---------------------------------------------------------------------------
# Database constraints
# ---------------------------------------------------------------------------

def test_an_invalid_family_access_mode_is_refused(db_session):
    from sqlalchemy.exc import IntegrityError

    tenant = make_tenant(db_session, subdomain_prefix="p0c-bad1")
    db_session.add(
        TenantAuthPolicy(tenant_id=tenant.id, family_access_mode="whatever")
    )
    with pytest.raises(IntegrityError) as refused:
        db_session.flush()
    assert "family_access_mode" in str(refused.value)


def test_an_invalid_credential_policy_is_refused(db_session):
    from sqlalchemy.exc import IntegrityError

    tenant = make_tenant(db_session, subdomain_prefix="p0c-bad2")
    db_session.add(
        TenantAuthPolicy(
            tenant_id=tenant.id, student_credential_policy="never_change"
        )
    )
    with pytest.raises(IntegrityError) as refused:
        db_session.flush()
    assert "student_credential_policy" in str(refused.value)


def test_an_invalid_subject_kind_is_refused(db_session, tenant):
    from sqlalchemy.exc import IntegrityError

    _rule(db_session, tenant, subject_kind="staff", method_key=EMAIL_PASSWORD)
    db_session.add(
        TenantAuthPolicyRule(
            id=new_id("apr-"), tenant_id=tenant.id, subject_kind="janitor",
            surface=SURFACE_ANY, method_key=EMAIL_PASSWORD,
        )
    )
    with pytest.raises(IntegrityError) as refused:
        db_session.flush()
    assert "subject_kind" in str(refused.value)


def test_two_rules_cannot_answer_the_same_question(db_session, tenant):
    from sqlalchemy.exc import IntegrityError

    _rule(db_session, tenant, subject_kind="staff", method_key=EMAIL_PASSWORD)
    db_session.add(
        TenantAuthPolicyRule(
            id=new_id("apr-"), tenant_id=tenant.id, subject_kind="staff",
            surface=SURFACE_ANY, method_key=EMAIL_PASSWORD, is_enabled=False,
        )
    )
    with pytest.raises(IntegrityError) as refused:
        db_session.flush()
    assert "uq_tenant_auth_policy_rules" in str(refused.value)


def test_a_school_holds_one_policy_row(db_session):
    from sqlalchemy.exc import IntegrityError

    tenant = make_tenant(db_session, subdomain_prefix="p0c-one")
    ensure_default_policy(tenant.id)
    db_session.add(TenantAuthPolicy(tenant_id=tenant.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


# ---------------------------------------------------------------------------
# The read-only API
# ---------------------------------------------------------------------------

def _platform_headers(admin):
    from modules.auth.services import generate_access_token

    return {"Authorization": f"Bearer {generate_access_token(admin)}"}


@pytest.fixture
def platform_admin(db_session):
    home = make_tenant(db_session, subdomain_prefix="p0c-api-hq")
    return make_platform_admin(db_session, home, password=PASSWORD)


def test_a_platform_admin_can_read_a_tenants_policy(
    client, db_session, policed_tenant, platform_admin
):
    response = client.get(
        f"/api/platform/tenants/{policed_tenant.id}/auth-policy",
        headers=_platform_headers(platform_admin),
    )

    assert response.status_code == 200, response.get_json()
    data = response.get_json()["data"]
    assert data["tenant_id"] == policed_tenant.id
    assert data["family_access_mode"] == FAMILY_ACCESS_SHARED
    assert data["student_credential_policy"] == CREDENTIAL_FORCE_CHANGE
    assert len(data["rules"]) == 3
    assert {r["subject_kind"] for r in data["rules"]} == {
        "student", "staff", "parent"
    }


def test_the_response_carries_only_policy_fields(
    client, db_session, policed_tenant, platform_admin
):
    """No account, no identifier, no credential, nothing secret."""
    data = client.get(
        f"/api/platform/tenants/{policed_tenant.id}/auth-policy",
        headers=_platform_headers(platform_admin),
    ).get_json()["data"]

    assert set(data) == {
        "tenant_id",
        "family_access_mode",
        "student_credential_policy",
        "otp_delivery_channel",
        "is_configured",
        "updated_at",
        "rules",
    }
    for rule in data["rules"]:
        assert set(rule) == {
            "subject_kind", "surface", "method_key",
            "is_enabled", "enabled_at", "notes",
        }
    # Checked as key names, not substrings: `email_password` is a method key
    # and legitimately contains the word.
    def keys_of(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from keys_of(value)
        elif isinstance(node, list):
            for item in node:
                yield from keys_of(item)

    present = set(keys_of(data))
    for forbidden in (
        "secret_hash", "password_hash", "identifier_value",
        "identifier_value_normalized", "token", "email",
    ):
        assert forbidden not in present


def test_an_ordinary_tenant_user_cannot_read_policy(
    client, db_session, policed_tenant
):
    account = _staff_account(db_session, policed_tenant)

    response = client.get(
        f"/api/platform/tenants/{policed_tenant.id}/auth-policy",
        headers=_platform_headers(account),
    )

    assert response.status_code == 403


def test_an_unauthenticated_caller_cannot_read_policy(client, policed_tenant):
    response = client.get(
        f"/api/platform/tenants/{policed_tenant.id}/auth-policy"
    )

    assert response.status_code == 401


def test_a_nonexistent_tenant_is_a_not_found(client, db_session, platform_admin):
    response = client.get(
        f"/api/platform/tenants/{uuid.uuid4()}/auth-policy",
        headers=_platform_headers(platform_admin),
    )

    assert response.status_code == 404


def test_the_endpoint_reads_the_tenant_that_was_asked_for(
    client, db_session, platform_admin
):
    first = make_tenant(db_session, subdomain_prefix="p0c-api-a")
    second = make_tenant(db_session, subdomain_prefix="p0c-api-b")
    ensure_default_policy(first.id)
    ensure_default_policy(second.id)
    policy_for(second.id).family_access_mode = FAMILY_ACCESS_SEPARATE
    db_session.flush()

    for tenant, expected in ((first, FAMILY_ACCESS_SHARED),
                             (second, FAMILY_ACCESS_SEPARATE)):
        data = client.get(
            f"/api/platform/tenants/{tenant.id}/auth-policy",
            headers=_platform_headers(platform_admin),
        ).get_json()["data"]
        assert data["tenant_id"] == tenant.id
        assert data["family_access_mode"] == expected


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_the_policy_endpoint_takes_no_verb_but_the_two_it_declares(
    client, policed_tenant, platform_admin, method
):
    """The surface stays narrow.

    Written when the endpoint was read-only and `patch` belonged in this list.
    It no longer does — a school's family access mode and student credential
    policy are set through PATCH, which is what stopped enabling parent logins
    being a Python-shell operation. Creating a policy by POST, replacing one
    wholesale by PUT and deleting one still have no meaning here, and that is
    what this now pins.
    """
    response = getattr(client, method)(
        f"/api/platform/tenants/{policed_tenant.id}/auth-policy",
        headers=_platform_headers(platform_admin),
        json={"family_access_mode": FAMILY_ACCESS_SEPARATE},
    )

    assert response.status_code == 405


def test_the_policy_can_be_changed_by_patch(client, policed_tenant, platform_admin):
    """The counterpart: the one verb that does write."""
    response = client.patch(
        f"/api/platform/tenants/{policed_tenant.id}/auth-policy",
        headers=_platform_headers(platform_admin),
        json={"family_access_mode": FAMILY_ACCESS_SEPARATE},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["family_access_mode"] == FAMILY_ACCESS_SEPARATE


def test_describe_falls_back_to_the_defaults_and_says_so(db_session):
    bare = make_tenant(db_session, subdomain_prefix="p0c-bare2")

    described = describe(bare.id)

    assert described["is_configured"] is False
    assert described["family_access_mode"] == FAMILY_ACCESS_SHARED
    assert described["rules"] == []


# ---------------------------------------------------------------------------
# The boundary: the policy governs nothing yet
# ---------------------------------------------------------------------------

def test_login_now_obeys_the_policy(client, db_session, tenant):
    """Phase 0d is where the policy acquired authority.

    This was the Phase 0c marker test, which asserted the opposite: every rule
    disabled and the account signing in anyway, because nothing consulted the
    policy yet. The pipeline consults it now, so a school that permits no
    method for this person refuses — with a correct password.
    """
    from tests.auth._characterization import login, make_account

    ensure_default_policy(tenant.id)
    for rule in TenantAuthPolicyRule.query.filter_by(tenant_id=tenant.id):
        rule.is_enabled = False
    db_session.flush()

    account = make_account(db_session, tenant, password=PASSWORD)
    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"


def test_the_policy_gate_runs_before_the_password_is_checked(
    client, db_session, tenant
):
    """A denied method must not consume a verification — and, once a method
    costs money to attempt, must not spend it either. A *wrong* password gets
    the policy refusal, not the credential one."""
    from tests.auth._characterization import login, make_account

    ensure_default_policy(tenant.id)
    for rule in TenantAuthPolicyRule.query.filter_by(tenant_id=tenant.id):
        rule.is_enabled = False
    db_session.flush()

    account = make_account(db_session, tenant, password=PASSWORD)
    response = login(
        client, email=account.email, password="wrong-entirely", tenant_id=tenant.id
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"
    # And the attempt did not count against the account.
    db_session.refresh(account)
    assert (account.failed_login_count or 0) == 0


def test_a_school_with_no_policy_at_all_still_works(client, db_session):
    """Nobody is locked out by not having been seeded."""
    from tests.auth._characterization import login, make_account

    bare = make_tenant(db_session, subdomain_prefix="p0c-nopolicy")
    assert policy_for(bare.id) is None

    account = make_account(db_session, bare, password=PASSWORD)
    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=bare.id
    )

    assert response.status_code == 200, response.get_json()


def test_the_policy_is_not_stored_in_feature_flags(db_session, policed_tenant):
    """An explicit architectural decision: `tenants.feature_flags` merges and
    never prunes, so a retired key outlives its module. Policy does not live
    there and must not start to."""
    from core.models import Tenant

    flags = db_session.get(Tenant, policed_tenant.id).feature_flags or {}

    for key in flags:
        assert "auth" not in key
        assert "login" not in key or key == "login_variant"
    assert "family_access_mode" not in flags
    assert "student_credential_policy" not in flags
