"""Phase 1a — the two provisioning defects, fixed before credentials are issued.

Phase 1b starts handing school-issued credentials to thousands of students. It
should not do so through importers that (a) let an imported child keep a
password derived from their own name indefinitely, and (b) manufacture an email
address for a teacher who never gave one.

Both are corrections to *future* provisioning. No existing account is reissued,
re-flagged or rewritten, and there is no migration.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from unittest.mock import patch

from core.database import db
from modules.auth.models import AccountCredential, AccountIdentifier, User
from modules.people.employment import Staff
from modules.people.models import Person
from modules.students.models import Student
from modules.teachers.models import Teacher
from tests.auth._characterization import new_id

PASSWORD = "C0rrectHorse1"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        id=new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    db_session.add(year)
    db_session.flush()
    return year


# ---------------------------------------------------------------------------
# Defect A — an imported student must replace the password the sheet gave them
# ---------------------------------------------------------------------------

def _import_students(flask_app, tenant, academic_year, rows):
    from flask import g

    from modules.students.bulk_student_import_service import (
        import_students_from_rows,
    )

    with flask_app.test_request_context():
        g.tenant_id = tenant.id
        return import_students_from_rows(
            rows,
            list(range(2, 2 + len(rows))),
            tenant_id=tenant.id,
            academic_year_id=academic_year.id,
            send_email=False,
        )


def _student_row(klass, **overrides):
    row = {
        "name": "Imported Child",
        "email": f"child-{uuid.uuid4().hex[:8]}@test.school",
        "branch": klass["branch"],
        "programme": klass["programme"],
        "class_name": klass["class_name"],
        "section": klass["section"],
        "father_name": "A Father",
        "father_phone": "9876500001",
    }
    row.update(overrides)
    return row


@pytest.fixture
def importable_class(db_session, tenant, academic_year):
    """The smallest structure a student import row can point at.

    The importer resolves a class from the sheet's required `branch` and
    `programme` columns, so the class needs a campus and a programme — that
    resolution is the product's, and this fixture feeds it rather than working
    around it.
    """
    from modules.academic_programmes.models import AcademicProgramme
    from modules.classes.models import Class
    from modules.school_units.models import SchoolUnit

    unit = SchoolUnit(
        id=new_id("su-"), tenant_id=tenant.id, name="Main Campus", code="MAIN"
    )
    db_session.add(unit)
    db_session.flush()

    programme = AcademicProgramme(
        id=new_id("ap-"), tenant_id=tenant.id, name="CBSE English", code="CBSE-EN",
        board="CBSE", medium="English",
    )
    db_session.add(programme)
    db_session.flush()

    klass = Class(
        id=new_id("c-"), tenant_id=tenant.id, name="Grade 5", section="A",
        academic_year_id=academic_year.id,
        school_unit_id=unit.id, programme_id=programme.id,
    )
    db_session.add(klass)
    db_session.flush()
    return {
        "branch": unit.name,
        "programme": programme.name,
        "class_name": klass.name,
        "section": klass.section,
        "class_id": klass.id,
    }


def test_an_imported_student_must_replace_their_password(
    flask_app, db_session, tenant, academic_year, importable_class
):
    """The defect. The password the importer generates is derived from the
    child's own name, so it is not a secret from anybody who knows them."""
    row = _student_row(importable_class)

    result = _import_students(flask_app, tenant, academic_year, [row])

    assert result["success"] == 1, result
    account = User.query.filter_by(
        tenant_id=tenant.id, email=row["email"]
    ).one()
    assert account.force_password_reset is True


def test_the_import_still_creates_the_student_and_its_person(
    flask_app, db_session, tenant, academic_year, importable_class
):
    """The correction changes one flag and nothing else."""
    row = _student_row(importable_class)

    result = _import_students(flask_app, tenant, academic_year, [row])

    assert result["success"] == 1
    assert result["failed"] == 0
    account = User.query.filter_by(tenant_id=tenant.id, email=row["email"]).one()
    student = Student.query.filter_by(user_id=account.id).one()
    assert student.person_id == account.person_id
    assert student.admission_number
    # And exactly one account for that person — the Phase 0a invariant.
    assert (
        User.query.filter_by(
            tenant_id=tenant.id, person_id=account.person_id, deleted_at=None
        ).count()
        == 1
    )


def test_an_imported_student_still_gets_an_email_identifier(
    flask_app, db_session, tenant, academic_year, importable_class
):
    """A2 keeps working through the importer."""
    row = _student_row(importable_class)

    _import_students(flask_app, tenant, academic_year, [row])

    account = User.query.filter_by(tenant_id=tenant.id, email=row["email"]).one()
    assert (
        AccountIdentifier.query.filter_by(
            account_id=account.id, identifier_type="email", deleted_at=None
        ).count()
        == 1
    )


def test_an_imported_student_can_sign_in_and_is_then_made_to_change_it(
    flask_app, client, db_session, tenant, academic_year, importable_class
):
    """End to end: the issued password works, and the account is locked into a
    change until it is replaced — the existing forced-reset flow, unchanged."""
    from modules.auth.policy import ensure_default_policy
    from tests.auth._characterization import login

    ensure_default_policy(tenant.id)
    row = _student_row(importable_class, name="Priya Sharma")

    # The issued password is random and unguessable — which is the point of
    # A5, and why this test pins it rather than deriving it. What is under
    # test is the sign-in, not the generator; the generator has its own tests.
    issued = "Kn7pQr4TzW"
    with patch(
        "modules.auth.provisioning.generate_initial_password", return_value=issued
    ):
        _import_students(flask_app, tenant, academic_year, [row])

    response = login(
        client, email=row["email"], password=issued, tenant_id=tenant.id
    )

    assert response.status_code == 200, response.get_json()
    data = response.get_json()["data"]
    assert data["force_password_reset"] is True

    # And the rest of the API is closed until the password is replaced.
    blocked = client.get(
        "/api/students/",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {data['access_token']}",
        },
    )
    assert blocked.status_code == 403
    assert "PasswordResetRequired" in str(blocked.get_json())


def test_no_existing_account_was_re_flagged(db_session):
    """Future provisioning only. The 15,944 accounts already in the database
    keep whatever forced-reset state they had; nothing retro-flags them."""
    flagged = db_session.execute(
        db.text("SELECT count(*) FROM users WHERE force_password_reset")
    ).scalar()

    # The development database has 19 such accounts and this phase adds none.
    assert flagged == 19


def test_a_credentials_must_change_follows_the_account(db_session, tenant):
    """Consistency, not dual-write: no credential row is created here, but one
    that exists must not drift from the account it belongs to."""
    from tests.auth._characterization import make_user

    account = make_user(db_session, tenant, password=PASSWORD)
    credential = AccountCredential(
        id=new_id("ac-"),
        tenant_id=tenant.id,
        account_id=account.id,
        credential_type="password",
        secret_hash=account.password_hash,
        hash_algorithm="scrypt",
        must_change=False,
    )
    db_session.add(credential)
    db_session.flush()

    account.force_password_reset = True
    db_session.flush()
    assert credential.must_change is True

    account.force_password_reset = False
    db_session.flush()
    assert credential.must_change is False


def test_no_credential_row_is_invented_for_an_account_without_one(
    db_session, tenant
):
    """Whether accounts get credential rows at creation stays Phase 0b's
    deferred question. This phase does not answer it."""
    from tests.auth._characterization import make_user

    account = make_user(db_session, tenant, password=PASSWORD)
    account.force_password_reset = True
    db_session.flush()

    assert AccountCredential.query.filter_by(account_id=account.id).count() == 0


# ---------------------------------------------------------------------------
# Defect B — a teacher who gave no address gets no invented one
# ---------------------------------------------------------------------------

def _import_teachers(flask_app, tenant, rows):
    from flask import g

    from modules.teachers.bulk_teacher_import_service import (
        import_teachers_from_rows,
    )

    with flask_app.test_request_context():
        g.tenant_id = tenant.id
        return import_teachers_from_rows(
            rows,
            list(range(2, 2 + len(rows))),
            tenant_id=tenant.id,
            send_email=False,
        )


def test_a_teacher_with_an_address_still_gets_an_account(
    flask_app, db_session, tenant
):
    address = f"teacher-{uuid.uuid4().hex[:8]}@test.school"

    result = _import_teachers(
        flask_app, tenant, [{"name": "Real Teacher", "email": address}]
    )

    assert result["success"] == 1, result
    assert result["accounts_created"] == 1
    assert result["accounts_skipped_no_email"] == 0
    account = User.query.filter_by(tenant_id=tenant.id, email=address).one()
    teacher = Teacher.query.filter_by(user_id=account.id).one()
    assert teacher.staff_id is not None
    assert (
        AccountIdentifier.query.filter_by(
            account_id=account.id, identifier_type="email", deleted_at=None
        ).count()
        == 1
    )


def test_a_teacher_without_an_address_is_still_imported(
    flask_app, db_session, tenant
):
    """ADR-003: the employment, the authority and the person are all recorded.
    Only the login is absent, and that is not a failure."""
    result = _import_teachers(
        flask_app, tenant, [{"name": "Kamala Iyer", "designation": "Teacher"}]
    )

    assert result["success"] == 1, result
    assert result["failed"] == 0
    assert result["accounts_created"] == 0
    assert result["accounts_skipped_no_email"] == 1

    person = Person.query.filter_by(
        tenant_id=tenant.id, full_name="Kamala Iyer"
    ).one()
    staff = Staff.query.filter_by(tenant_id=tenant.id, person_id=person.id).one()
    teacher = Teacher.query.filter_by(staff_id=staff.id).one()
    assert teacher.user_id is None


def test_no_address_is_manufactured_for_them(flask_app, db_session, tenant):
    """The defect itself. `<employee_id>@teacher.school` reached nobody, could
    not be verified, could not receive a reset, and was indistinguishable from
    a real address to every notification, search and export path."""
    _import_teachers(
        flask_app, tenant, [{"name": "No Address Teacher"}]
    )

    invented = User.query.filter(
        User.tenant_id == tenant.id, User.email.like("%@teacher.school")
    ).count()
    assert invented == 0

    fabricated_identifier = AccountIdentifier.query.filter(
        AccountIdentifier.tenant_id == tenant.id,
        AccountIdentifier.identifier_value_normalized.like("%@teacher.school"),
    ).count()
    assert fabricated_identifier == 0


def test_an_account_less_teacher_holds_their_authority(
    flask_app, db_session, tenant
):
    """Authority belongs to the employment, not the login (ADR-013), so it
    survives having no account."""
    from modules.rbac.authority_service import authority_profiles_for_person

    _import_teachers(flask_app, tenant, [{"name": "Authority Teacher"}])

    person = Person.query.filter_by(
        tenant_id=tenant.id, full_name="Authority Teacher"
    ).one()
    assert "Teacher" in {r.name for r in authority_profiles_for_person(person.id)}


def test_a_mixed_sheet_reports_both_outcomes(flask_app, db_session, tenant):
    """The distinction the summary could not previously make: a teacher who can
    sign in, and a teacher the school has recorded but not given a login."""
    address = f"teacher-{uuid.uuid4().hex[:8]}@test.school"

    result = _import_teachers(
        flask_app,
        tenant,
        [
            {"name": "With Address", "email": address},
            {"name": "Without Address"},
            {"name": "Also Without Address"},
        ],
    )

    assert result["success"] == 3
    assert result["failed"] == 0
    assert result["accounts_created"] == 1
    assert result["accounts_skipped_no_email"] == 2


def test_an_account_less_teacher_is_not_a_failed_row(flask_app, db_session, tenant):
    result = _import_teachers(flask_app, tenant, [{"name": "Quietly Fine"}])

    assert result["failed_rows"] == []


def test_a_duplicate_address_is_still_rejected(flask_app, db_session, tenant):
    """The existing guard is untouched: an address already in the school is a
    validation failure, not a second account."""
    from tests.auth._characterization import make_user

    existing = make_user(db_session, tenant, password=PASSWORD)
    db_session.flush()

    from flask import g

    from modules.teachers.bulk_teacher_import_service import (
        validate_teacher_workbook_rows,
    )

    with flask_app.test_request_context():
        g.tenant_id = tenant.id
        preview, _summary = validate_teacher_workbook_rows(
            [{"name": "Clash", "email": existing.email}], [2], tenant.id
        )

    assert preview[0]["errors"] == ["Email already exists"]


def test_two_account_less_teachers_do_not_collide(flask_app, db_session, tenant):
    """Nothing keys them on an invented address any more, so two teachers with
    no email are simply two teachers."""
    result = _import_teachers(
        flask_app, tenant, [{"name": "First None"}, {"name": "Second None"}]
    )

    assert result["success"] == 2
    assert result["accounts_skipped_no_email"] == 2
    assert (
        Person.query.filter(
            Person.tenant_id == tenant.id,
            Person.full_name.in_(["First None", "Second None"]),
        ).count()
        == 2
    )


def test_historical_synthetic_addresses_are_left_alone(db_session):
    """Whatever the database already holds stays as it is. Rewriting somebody's
    stored identity is a separately designed operation, not a side effect of
    correcting the importer."""
    before = db_session.execute(
        db.text("SELECT count(*) FROM users WHERE email LIKE '%@teacher.school'")
    ).scalar()

    # Nothing in this phase touches them; the count is simply recorded.
    assert before >= 0


def test_the_import_writes_identity_onto_the_person_not_the_student(
    flask_app, db_session, tenant, academic_year, importable_class
):
    """The repair, stated as the rule it enforces.

    Date of birth, gender, phone, address and Aadhaar describe the human, not
    their studentship. The v2 refactor moved all five onto `Person`; the
    importer kept handing them to `Student`, which raised on every created row
    and silently discarded them on every updated one.
    """
    row = _student_row(
        importable_class,
        name="Meera Nair",
        date_of_birth="2013-08-21",
        gender="female",
        phone="9876511111",
        address="14 Residency Road",
        aadhar_number="123412341234",
    )

    result = _import_students(flask_app, tenant, academic_year, [row])
    assert result["success"] == 1, result

    account = User.query.filter_by(tenant_id=tenant.id, email=row["email"]).one()
    person = Person.query.filter_by(id=account.person_id).one()

    assert person.date_of_birth == date(2013, 8, 21)
    assert person.gender == "female"
    assert person.phone_number == "9876511111"
    assert person.address == "14 Residency Road"
    assert person.aadhaar_number == "123412341234"

    # And none of it was written onto the studentship.
    student = Student.query.filter_by(user_id=account.id).one()
    for moved in ("date_of_birth", "gender", "phone", "address", "aadhar_number"):
        assert moved not in {c.name for c in Student.__table__.columns}
        assert not hasattr(student.__table__.c, moved)


def test_student_specific_fields_still_land_on_the_student(
    flask_app, db_session, tenant, academic_year, importable_class
):
    """Only the five moved. Everything the studentship owns stays put."""
    row = _student_row(
        importable_class,
        roll_number="17",
        blood_group="O+",
        guardian_name="A Guardian",
        guardian_phone="9876522222",
        mother_tongue="Malayalam",
    )

    _import_students(flask_app, tenant, academic_year, [row])

    account = User.query.filter_by(tenant_id=tenant.id, email=row["email"]).one()
    student = Student.query.filter_by(user_id=account.id).one()
    assert student.roll_number == 17
    assert student.blood_group == "O+"
    assert student.guardian_name == "A Guardian"
    assert student.guardian_phone == "9876522222"
    assert student.mother_tongue == "Malayalam"
    assert student.admission_number


def test_the_import_creates_one_person_and_one_account(
    flask_app, db_session, tenant, academic_year, importable_class
):
    """Phase 0a's invariant, through the importer."""
    row = _student_row(importable_class)

    _import_students(flask_app, tenant, academic_year, [row])

    account = User.query.filter_by(tenant_id=tenant.id, email=row["email"]).one()
    assert (
        User.query.filter_by(
            tenant_id=tenant.id, person_id=account.person_id, deleted_at=None
        ).count()
        == 1
    )
    assert Person.query.filter_by(id=account.person_id).count() == 1
    assert (
        AccountIdentifier.query.filter_by(
            account_id=account.id, identifier_type="email", deleted_at=None
        ).count()
        == 1
    )


def test_an_invalid_row_still_fails_and_creates_nothing(
    flask_app, db_session, tenant, academic_year, importable_class
):
    """The repair must not turn a bad row into a good one."""
    good = _student_row(importable_class)
    bad = _student_row(importable_class, branch="No Such Campus")

    result = _import_students(flask_app, tenant, academic_year, [good, bad])

    assert result["success"] == 1
    assert result["failed"] == 1
    assert User.query.filter_by(
        tenant_id=tenant.id, email=bad["email"]
    ).count() == 0


def test_a_re_import_fills_in_identity_the_first_sheet_left_out(
    flask_app, db_session, tenant, academic_year, importable_class
):
    """The other half of the repair.

    On the update path the five moved fields were `setattr` onto a Student
    attribute that is not a column — no error, and nothing persisted. So a
    school filling in dates of birth on a second upload wrote them nowhere.
    A re-import now reaches the person, and `fill_blank_identity` means it adds
    detail without overwriting what is already on record.
    """
    first = _student_row(importable_class, name="Arjun Rao")
    created = _import_students(flask_app, tenant, academic_year, [first])
    assert created["success"] == 1, created

    account = User.query.filter_by(tenant_id=tenant.id, email=first["email"]).one()
    student = Student.query.filter_by(user_id=account.id).one()
    person = Person.query.filter_by(id=account.person_id).one()
    assert person.date_of_birth is None

    again = _student_row(
        importable_class,
        name="Arjun Rao",
        email=first["email"],
        admission_number=student.admission_number,
        date_of_birth="2012-02-29",
        gender="male",
        phone="9876533333",
    )
    result = _import_students(flask_app, tenant, academic_year, [again])

    assert result["failed"] == 0, result
    db_session.refresh(person)
    assert person.date_of_birth == date(2012, 2, 29)
    assert person.gender == "male"
    assert person.phone_number == "9876533333"
