"""Switching a module off must not break the modules that are still on.

A school buys Nexchool and turns hostel off, or has no buses, or does its fees
in a different system. Every one of those is a supported way to run a school,
not a degraded install — so the parts they *did* buy have to keep working.

The risk is not the disabled module: its own routes are supposed to refuse.
The risk is everything that reads it. The dashboard totals ridership. The
student page shows a bus stop. Fourteen modules send notifications. Any of
those can turn "transport is off" into a 500 on a page that has nothing to do
with transport.

So this sweeps every parameterless GET the API exposes, once with everything
on and once per optional feature turned off, and holds them to the baseline: a
route that answered before must still answer. It reads the URL map rather than
a hand-written list, so a route added next month is covered without anyone
remembering to add it here.

A 403 is a pass. Refusing is the feature working. Only 5xx is a break.
"""

from __future__ import annotations

import uuid

import pytest

from core.feature_flags import OPTIONAL_FEATURES

# Routes that cannot be swept: they never return, or they are not the tenant's.
SKIP_ROUTES = {
    "/api/notifications/stream",   # server-sent events; holds the connection open
    "/api/health",                 # no tenant, no auth
    "/api/graphql",                # GET is the playground, not an operation
}
SKIP_PREFIXES = (
    "/api/platform/",              # the company's control plane, not a tenant's
    "/api/auth/",                  # pre-auth surface, deliberately ungated
)


def _sweepable_routes(flask_app) -> list[str]:
    """Every GET a signed-in admin could land on without knowing an id."""
    routes = {
        str(rule)
        for rule in flask_app.url_map.iter_rules()
        if "GET" in rule.methods
        and not rule.arguments
        and str(rule).startswith("/api/")
        and str(rule) not in SKIP_ROUTES
        and not str(rule).startswith(SKIP_PREFIXES)
    }
    return sorted(routes)


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def admin_headers(db_session, tenant):
    """A school admin holding everything, so nothing is hidden by permissions.

    The point is to isolate the feature flag as the only variable: a 403 in the
    sweep then means "this feature is off", never "this user lacks the grant".
    """
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Role
    from modules.rbac.role_seeder import seed_roles_for_tenant
    from tests.conftest import grant_profile_to

    seed_roles_for_tenant(tenant.id)
    admin_role = Role.query.filter_by(name="Admin", tenant_id=tenant.id).first()

    user = User(
        id=f"u-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant.id,
        email=f"sweep-admin-{uuid.uuid4().hex[:8]}@test.school",
        name="Sweep Admin",
        email_verified=True,
    )
    user.set_password("Password123")
    db_session.add(user)
    db_session.flush()
    grant_profile_to(user, admin_role.id)

    token = generate_access_token(user)
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant.id}


def _set_flags(db_session, tenant, **overrides):
    """Rewrite the tenant's flag map. Absent keys stay enabled by default."""
    tenant.feature_flags = {key: True for key in OPTIONAL_FEATURES} | overrides
    db_session.flush()


def _sweep(client, headers, routes) -> dict[str, int]:
    """Status code per route. Never raises — a crash is the finding."""
    statuses = {}
    for route in routes:
        response = client.get(route, headers=headers)
        statuses[route] = response.status_code
    return statuses


@pytest.fixture
def baseline(client, admin_headers, db_session, tenant, flask_app):
    """What the API does with every feature on, for this empty tenant.

    Some routes fail for reasons that have nothing to do with flags — a tenant
    with no academic year, say. Those are somebody else's bug; comparing
    against a baseline rather than against 200 keeps this test about the one
    thing it is for.
    """
    _set_flags(db_session, tenant)
    return _sweep(client, admin_headers, _sweepable_routes(flask_app))


@pytest.mark.parametrize("feature", OPTIONAL_FEATURES)
def test_turning_a_feature_off_breaks_nothing_else(
    feature, client, admin_headers, db_session, tenant, flask_app, baseline
):
    """Disable one module; every route that worked before must still work.

    The failure this catches is the quiet kind: a dashboard that read transport
    directly, a student serializer that assumed a fee record exists. Nobody
    notices until a school that never bought the module opens the page.
    """
    _set_flags(db_session, tenant, **{feature: False})
    after = _sweep(client, admin_headers, _sweepable_routes(flask_app))

    broke = [
        f"{route}: {baseline[route]} → {status}"
        for route, status in after.items()
        if status >= 500 and baseline.get(route, 500) < 500
    ]

    assert not broke, (
        f"Turning off '{feature}' broke {len(broke)} route(s) that belong to "
        f"other modules:\n  " + "\n  ".join(broke)
    )


@pytest.fixture
def a_small_school(db_session, tenant):
    """A year, a class, a child in it, a teacher responsible for it.

    The empty-tenant sweep above misses the serializers, because a list with
    nothing in it never reaches the code that reads across modules. Most of
    the interesting damage — a student row that wants a bus stop, a class row
    that wants a fee structure — only happens once there is a row to serialize.
    """
    from datetime import date

    from modules.academics.academic_year.models import AcademicYear
    from modules.auth.models import User
    from modules.classes.models import Class
    from modules.students.models import Student
    from modules.teachers.models import Teacher
    from tests.conftest import employ_for

    def _uid(prefix):
        return f"{prefix}{uuid.uuid4().hex[:12]}"

    year = AcademicYear(
        id=_uid("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(year)
    db_session.flush()

    cls = Class(
        id=_uid("c-"), tenant_id=tenant.id, name="Grade 5", section="A",
        academic_year_id=year.id,
    )
    db_session.add(cls)
    db_session.flush()

    suffix = uuid.uuid4().hex[:8]
    teacher_account = User(
        id=_uid("u-"), tenant_id=tenant.id, email=f"teach-{suffix}@test.school",
        password_hash="x" * 60, name="Class Teacher",
    )
    db_session.add(teacher_account)
    db_session.flush()
    teacher = Teacher(
        id=_uid("t-"), tenant_id=tenant.id, user_id=teacher_account.id,
        staff_id=employ_for(teacher_account, employee_number=f"EMP-{suffix}").id,
    )
    db_session.add(teacher)

    child_account = User(
        id=_uid("u-"), tenant_id=tenant.id, email=f"child-{suffix}@test.school",
        password_hash="x" * 60, name="Enrolled Child",
    )
    db_session.add(child_account)
    db_session.flush()
    child = Student(
        id=_uid("s-"), tenant_id=tenant.id, user_id=child_account.id,
        person_id=child_account.person_id, admission_number=f"ADM-{suffix}",
        academic_year_id=year.id, class_id=cls.id,
    )
    db_session.add(child)
    db_session.flush()

    from modules.classes.services import assign_teacher_to_class

    assign_teacher_to_class(cls.id, teacher.id, is_class_teacher=True)

    return {"class_id": cls.id, "student_id": child.id, "teacher_id": teacher.id}


def _populated_routes(ids: dict) -> list[str]:
    """The pages an admin actually opens, on a school that has data in it.

    Detail routes and the query variants that pull another module in — the
    student list only asks transport for stop names when the caller opts in,
    so sweeping the bare URL would never exercise it.
    """
    return [
        "/api/dashboard/",
        "/api/academics/dashboard",
        "/api/academics/health",
        "/api/academics/overview",
        "/api/students/",
        "/api/students/?include_transport_summary=true",
        "/api/students/export",
        "/api/classes/",
        "/api/classes/stats",
        "/api/classes/export",
        "/api/teachers/",
        f"/api/students/{ids['student_id']}",
        f"/api/classes/{ids['class_id']}",
        f"/api/teachers/{ids['teacher_id']}",
    ]


@pytest.mark.parametrize("feature", OPTIONAL_FEATURES)
def test_a_school_with_data_survives_a_feature_being_off(
    feature, client, admin_headers, db_session, tenant, a_small_school
):
    """Same contract as above, but against rows rather than empty tables."""
    routes = _populated_routes(a_small_school)

    _set_flags(db_session, tenant)
    before = _sweep(client, admin_headers, routes)

    _set_flags(db_session, tenant, **{feature: False})
    after = _sweep(client, admin_headers, routes)

    broke = [
        f"{route}: {before[route]} → {status}"
        for route, status in after.items()
        if status >= 500 and before.get(route, 500) < 500
    ]

    assert not broke, (
        f"With '{feature}' off, {len(broke)} page(s) belonging to other modules "
        f"failed on a school that has data:\n  " + "\n  ".join(broke)
    )


def test_a_disabled_feature_actually_refuses(
    client, admin_headers, db_session, tenant, baseline
):
    """The other half: gating has to bite, or the sweep above proves nothing.

    A pass here plus a pass above is the whole contract — off means refused,
    and refused means nothing else notices.
    """
    checks = [
        ("transport", "/api/transport/buses"),
        ("hostel", "/api/hostel/hostels"),
        ("fees_management", "/api/finance/summary"),
        ("attendance", "/api/attendance/list"),
        ("notifications", "/api/notifications"),
    ]

    still_answering = []
    for feature, route in checks:
        if baseline.get(route, 500) >= 500:
            continue  # never worked here; nothing to prove
        _set_flags(db_session, tenant, **{feature: False})
        if client.get(route, headers=admin_headers).status_code != 403:
            still_answering.append(f"{route} (feature '{feature}')")

    assert not still_answering, (
        "Disabled features must refuse with 403; these answered anyway:\n  "
        + "\n  ".join(still_answering)
    )
