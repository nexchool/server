"""What actually keeps one school's data away from another.

Three separate mechanisms, each with a different failure mode, each pinned
here because each has already failed once or was found unenforced:

1. **Inheritance applies the ORM scope.** `core/database.py` passes
   `TenantBaseModel` to `with_loader_criteria`, so inheriting is the whole
   opt-in. Three models used to declare `__tenant_scoped__ = True` on a plain
   `db.Model` — a flag nothing read — and were silently unscoped.

2. **The database refuses cross-tenant authority.** Composite
   `(tenant_id, id)` foreign keys make it impossible to name another school's
   Role or Staff from an authority row, however the query is written.

3. **The scope is inert outside a request.** Celery, scripts and seeds get no
   filtering at all. That is by design — jobs are platform-wide — but it is
   the fact most likely to be forgotten, so it is stated as a test rather
   than a comment.
"""

from __future__ import annotations

import uuid

import pytest
from flask import g
from sqlalchemy.exc import IntegrityError

from core.database import db
from core.models import TenantBaseModel


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# 1. Inheritance is the opt-in
# ---------------------------------------------------------------------------

# Models that hold one school's data and must therefore be scoped. Named
# individually rather than discovered, so adding a model to the codebase
# cannot quietly satisfy this test.
SCOPED_MODELS = [
    ("modules.audit.models", "TenantAuditLog"),
    ("modules.school_setup.models", "SetupModuleEvent"),
    ("modules.school_setup.models", "DataPurgeLog"),
    ("modules.students.models", "Student"),
    ("modules.teachers.models", "Teacher"),
    ("modules.people.models", "Person"),
    ("modules.rbac.models", "Role"),
    ("modules.rbac.models", "AuthorityDelegation"),
    ("modules.attendance.models", "AttendanceCorrection"),
    ("modules.people.employment", "StaffLifecycleEvent"),
    ("modules.students.models", "StudentLifecycleEvent"),
    ("modules.students.models", "AdmissionApplication"),
]


@pytest.mark.parametrize("module_path,class_name", SCOPED_MODELS)
def test_tenant_owned_models_inherit_the_scope(module_path, class_name):
    model = getattr(__import__(module_path, fromlist=[class_name]), class_name)
    assert issubclass(model, TenantBaseModel), (
        f"{class_name} holds tenant data but does not inherit TenantBaseModel, "
        "so core/database.py never filters it. Inheriting is the only opt-in — "
        "no annotation or flag applies the scope."
    )


def test_no_model_declares_a_scoping_flag_that_nothing_reads():
    """`__tenant_scoped__` was removed; it must not come back.

    It read like an opt-in and was not one: three models declared it True and
    were unscoped for as long as they existed.
    """
    import pathlib

    server_root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in server_root.rglob("*.py"):
        if "venv" in path.parts or "migrations" in path.parts:
            continue
        for lineno, line in enumerate(
            path.read_text(errors="ignore").splitlines(), start=1
        ):
            stripped = line.strip()
            if stripped.startswith("__tenant_scoped__"):
                offenders.append(f"{path.relative_to(server_root)}:{lineno}")
    assert not offenders, (
        "__tenant_scoped__ is not read by the scoping mechanism; a model that "
        f"declares it is not scoped by it. Found at: {offenders}"
    )


# ---------------------------------------------------------------------------
# 2. The database refuses cross-tenant authority
# ---------------------------------------------------------------------------

@pytest.fixture
def other_tenant(db_session):
    from core.models import Tenant

    other = Tenant(
        id=_new_id("t-"),
        name="Other School",
        subdomain=f"other-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(other)
    db_session.flush()
    return other


def _role_in(db_session, tenant, name="Principal"):
    from modules.rbac.models import Role

    role = Role(id=_new_id("r-"), tenant_id=tenant.id, name=f"{name}-{uuid.uuid4().hex[:4]}")
    db_session.add(role)
    db_session.flush()
    return role


def _staff_in(db_session, tenant):
    from modules.people.employment import Staff
    from modules.people.models import Person

    person = Person(
        id=_new_id("p-"), tenant_id=tenant.id, full_name="Someone Employed"
    )
    db_session.add(person)
    db_session.flush()
    staff = Staff(
        id=_new_id("s-"),
        tenant_id=tenant.id,
        person_id=person.id,
        employee_number=f"EMP-{uuid.uuid4().hex[:6]}",
        employment_status="working",
    )
    db_session.add(staff)
    db_session.flush()
    return staff


def test_authority_cannot_name_another_schools_role(db_session, tenant, other_tenant):
    """A grant in school A must not reference a Role owned by school B."""
    from modules.rbac.models import StaffAuthority

    ours = _staff_in(db_session, tenant)
    theirs = _role_in(db_session, other_tenant)

    db_session.add(
        StaffAuthority(
            id=_new_id("sa-"), tenant_id=tenant.id, staff_id=ours.id, role_id=theirs.id
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_delegation_cannot_lend_another_schools_authority(
    db_session, tenant, other_tenant
):
    """The table 088 missed: lending a Role that belongs to another school."""
    from datetime import date

    from modules.rbac.models import AuthorityDelegation

    lender = _staff_in(db_session, tenant)
    borrower = _staff_in(db_session, tenant)
    foreign_role = _role_in(db_session, other_tenant)

    db_session.add(
        AuthorityDelegation(
            id=_new_id("ad-"),
            tenant_id=tenant.id,
            role_id=foreign_role.id,
            from_staff_id=lender.id,
            to_staff_id=borrower.id,
            effective_from=date(2026, 6, 1),
            effective_to=date(2026, 6, 30),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_delegation_cannot_reach_another_schools_employment(
    db_session, tenant, other_tenant
):
    """The employment side: `staff` had no composite guard at all until 097."""
    from datetime import date

    from modules.rbac.models import AuthorityDelegation

    ours = _staff_in(db_session, tenant)
    theirs = _staff_in(db_session, other_tenant)
    role = _role_in(db_session, tenant)

    db_session.add(
        AuthorityDelegation(
            id=_new_id("ad-"),
            tenant_id=tenant.id,
            role_id=role.id,
            from_staff_id=ours.id,
            to_staff_id=theirs.id,  # another school's employment
            effective_from=date(2026, 6, 1),
            effective_to=date(2026, 6, 30),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# ---------------------------------------------------------------------------
# 3. The scope protects requests, not every query ever run
# ---------------------------------------------------------------------------

def test_the_orm_scope_does_not_apply_without_a_request(db_session, tenant, other_tenant):
    """Stated, not assumed: a background job sees every tenant.

    `core/database.py` returns early when there is no request context. Any
    Celery task, script or seed that must stay inside one tenant has to filter
    for itself — this test exists so that is a documented property rather than
    a surprise found in production.
    """
    from modules.audit.models import TenantAuditLog

    for owner in (tenant, other_tenant):
        db_session.add(
            TenantAuditLog(
                id=_new_id("tal-"),
                tenant_id=owner.id,
                actor_name="Someone",
                actor_role="admin",
                module="finance",
                action="test",
                resource_type="test",
                description="audit row",
            )
        )
    db_session.flush()

    # No request context here — the listener never fires.
    seen = {
        row.tenant_id
        for row in TenantAuditLog.query.filter(
            TenantAuditLog.tenant_id.in_([tenant.id, other_tenant.id])
        ).all()
    }
    assert seen == {tenant.id, other_tenant.id}


def test_the_orm_scope_applies_inside_a_request(flask_app, db_session, tenant, other_tenant):
    """The same query, inside a request, sees only the resolved tenant."""
    from modules.audit.models import TenantAuditLog

    for owner in (tenant, other_tenant):
        db_session.add(
            TenantAuditLog(
                id=_new_id("tal-"),
                tenant_id=owner.id,
                actor_name="Someone",
                actor_role="admin",
                module="finance",
                action="test",
                resource_type="test",
                description="audit row",
            )
        )
    db_session.flush()

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        seen = {
            row.tenant_id
            for row in TenantAuditLog.query.filter(
                TenantAuditLog.tenant_id.in_([tenant.id, other_tenant.id])
            ).all()
        }
    assert seen == {tenant.id}, (
        "TenantAuditLog is not being scoped inside a request — it must inherit "
        "TenantBaseModel for core/database.py to filter it."
    )


# ---------------------------------------------------------------------------
# 4. An audience cannot name another school's rows
# ---------------------------------------------------------------------------

def test_an_announcement_cannot_address_another_schools_class(
    flask_app, db_session, tenant, other_tenant
):
    """The audience is resolved later, in a task, where no scope applies.

    So the ids are checked while a tenant is still in context. Without this,
    publishing to a foreign class id wrote that school's teachers into this
    school's recipient rows — and told the sender which of their class ids
    exist.
    """
    from modules.announcements.services import ValidationError, _validate_audience
    from modules.classes.models import Class

    from datetime import date

    from modules.academics.academic_year.models import AcademicYear

    their_year = AcademicYear(
        id=_new_id("ay-"), tenant_id=other_tenant.id,
        name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(their_year)
    db_session.flush()
    theirs = Class(
        id=_new_id("c-"), tenant_id=other_tenant.id, name="Grade 9", section="A",
        academic_year_id=their_year.id,
    )
    db_session.add(theirs)
    db_session.flush()

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        with pytest.raises(ValidationError):
            _validate_audience({"scope": "classes", "class_ids": [theirs.id]})
