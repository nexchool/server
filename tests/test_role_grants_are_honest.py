"""What each seeded role holds, and what it takes to change that.

Two things used to make role grants drift silently, and one still does.

The first is fixed: there were two definitions of the same four roles —
`scripts/seed_rbac.py` and `modules/rbac/role_seeder.py` — kept in step by a
comment, so a tenant's authority depended on which seeder had made it. Both now
read `modules/rbac/catalog.py`. The tests below assert that rather than assert
the two agree, because "they agree" was the old guard and it passed right up
until someone edited one file.

The second is still true and deliberate: `seed_roles_for_tenant` runs on every
login and only ever adds. Removing a key from the catalogue changes nothing
anywhere until somebody reconciles — which is why taking `school_setup.read` off
the Teacher role needed migration 103. `reconcile=True` is that path, and it is
off by default because an operator's hand-made grant should not vanish because
somebody signed in.
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid

import pytest

SERVER = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def catalogue():
    from modules.rbac.catalog import DEFAULT_ROLES

    return DEFAULT_ROLES


def _permissions(role_spec) -> set:
    return set(role_spec["permissions"])


# ---------------------------------------------------------------------------
# One definition
# ---------------------------------------------------------------------------

def test_the_runtime_seeder_reads_the_catalogue_rather_than_its_own_copy():
    from modules.rbac.catalog import DEFAULT_ROLES
    from modules.rbac.role_seeder import DEFAULT_ROLES as via_seeder

    assert via_seeder is DEFAULT_ROLES


def test_the_cli_reads_the_catalogue_rather_than_its_own_copy():
    """`seed_rbac.ROLES` keeps its old shape but must be derived, not written.

    Loaded from the file rather than imported so this notices a literal being
    pasted back in, which is exactly the regression worth catching.
    """
    spec = importlib.util.spec_from_file_location(
        "_seed_rbac_for_test", SERVER / "scripts" / "seed_rbac.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from modules.rbac.catalog import DEFAULT_ROLES, PERMISSIONS

    assert module.PERMISSIONS is PERMISSIONS
    assert set(module.ROLES) == set(DEFAULT_ROLES)
    for role, entry in module.ROLES.items():
        assert entry["permissions"] is DEFAULT_ROLES[role]["permissions"]

    source = (SERVER / "scripts" / "seed_rbac.py").read_text()
    assert "'user.manage'" not in source and '"user.manage"' not in source, (
        "seed_rbac.py has a permission literal again — the definitions belong "
        "in modules/rbac/catalog.py, imported by both seeders"
    )


# ---------------------------------------------------------------------------
# What the roles hold
# ---------------------------------------------------------------------------

def test_a_teacher_does_not_hold_the_schools_onboarding_authority(catalogue):
    """Standing a school up is the platform operator's work, done in the panel.

    `school_setup.read` answers "how far has onboarding got" — not a question a
    teacher asks. It was granted only to let a teacher read the mediums and
    subject contexts; those reads now accept `class_subject.read`, which is the
    authority a teacher actually holds. See debt 33 and migration 103.
    """
    held = {k for k in _permissions(catalogue["Teacher"]) if k.startswith("school_setup")}
    assert held == set(), f"Teacher holds {sorted(held)}"


def test_a_teacher_can_still_read_class_subject_configuration(catalogue):
    """The other half of the change above.

    Removing the setup key is only correct because this one is present — the
    mediums and subject-context reads accept it. Losing it would take the
    medium and subject-context lists away from every teacher.
    """
    assert "class_subject.read" in _permissions(catalogue["Teacher"])


def test_the_reads_a_teacher_needs_accept_the_key_a_teacher_holds():
    """`class_subject.read` must appear in the guards, not just in the role.

    Asserted against the route modules rather than a live request because the
    pairing is what regresses: someone tightens a guard back to
    `class_subject.manage` and the teacher-facing list quietly 403s.
    """
    from modules.academics import resolvers as academics_resolvers
    from modules.subject_contexts import routes as context_routes

    assert context_routes.PERM_CS_READ == "class_subject.read"
    assert academics_resolvers.PERM_CLASS_SUBJECT_READ == "class_subject.read"

    source = pathlib.Path(context_routes.__file__).read_text()
    assert "PERM_CS_READ)" in source, (
        f"{context_routes.__name__} defines the read key but no guard accepts it"
    )

    # The medium list is GraphQL now — its REST route is gone — so the guard is
    # read off the field itself rather than out of a source file. `requires_any`
    # spells its keys into the guard class's name, which makes the real object
    # answerable without reaching into a closure.
    mediums = next(
        field
        for field in academics_resolvers.AcademicsQuery.__strawberry_definition__.fields
        if field.python_name == "mediums"
    )
    accepted = " ".join(guard.__name__ for guard in mediums.permission_classes)
    assert "class_subject_read" in accepted, (
        "the medium list no longer accepts the key a teacher actually holds"
    )


# ---------------------------------------------------------------------------
# Taking a grant away
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_tenant(flask_app, db_session, tenant):
    """This tenant's four default roles, seeded from the catalogue."""
    from modules.rbac.catalog import PERMISSIONS
    from modules.rbac.models import Permission
    from modules.rbac.role_seeder import seed_roles_for_tenant

    for name, description in PERMISSIONS:
        if not Permission.query.filter_by(name=name).first():
            db_session.add(Permission(name=name, description=description))
    db_session.flush()

    with flask_app.test_request_context("/"):
        seed_roles_for_tenant(tenant.id)
    return tenant


def _held_by(tenant_id, role_name) -> set:
    from core.database import db
    from modules.rbac.models import Permission, Role, RolePermission

    role = Role.query.filter_by(name=role_name, tenant_id=tenant_id).first()
    rows = (
        db.session.query(Permission.name)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .filter(RolePermission.role_id == role.id)
        .all()
    )
    return {name for (name,) in rows}


def _grant_extra(db_session, tenant_id, role_name, key):
    """A grant the catalogue does not name — what an operator's curl leaves."""
    from modules.rbac.models import Permission, Role, RolePermission

    permission = Permission.query.filter_by(name=key).first()
    if permission is None:
        permission = Permission(name=key, description="added by hand")
        db_session.add(permission)
        db_session.flush()
    role = Role.query.filter_by(name=role_name, tenant_id=tenant_id).first()
    db_session.add(
        RolePermission(
            tenant_id=tenant_id, role_id=role.id, permission_id=permission.id
        )
    )
    db_session.flush()


def test_signing_in_does_not_take_away_a_grant_made_by_hand(
    flask_app, db_session, seeded_tenant
):
    """The default is add-only, and that is the point.

    `seed_roles_for_tenant` runs on every login. If it reconciled there, an
    operator who granted a key deliberately would lose it the next time anyone
    signed in, with nothing to show why.
    """
    from modules.rbac.role_seeder import seed_roles_for_tenant

    _grant_extra(db_session, seeded_tenant.id, "Admin", "zz.granted.by.hand")

    with flask_app.test_request_context("/"):
        seed_roles_for_tenant(seeded_tenant.id)

    assert "zz.granted.by.hand" in _held_by(seeded_tenant.id, "Admin")


def test_reconciling_takes_away_what_the_catalogue_does_not_grant(
    flask_app, db_session, seeded_tenant
):
    """The revocation path that did not exist, and needed migration 103."""
    from modules.rbac.role_seeder import seed_roles_for_tenant

    _grant_extra(db_session, seeded_tenant.id, "Admin", "zz.granted.by.hand")
    assert "zz.granted.by.hand" in _held_by(seeded_tenant.id, "Admin")

    with flask_app.test_request_context("/"):
        seed_roles_for_tenant(seeded_tenant.id, reconcile=True)

    assert "zz.granted.by.hand" not in _held_by(seeded_tenant.id, "Admin")


def test_reconciling_keeps_everything_the_catalogue_does_grant(
    flask_app, db_session, seeded_tenant, catalogue
):
    """Guards the obvious way to get this wrong: revoking the lot."""
    from modules.rbac.role_seeder import seed_roles_for_tenant

    with flask_app.test_request_context("/"):
        seed_roles_for_tenant(seeded_tenant.id, reconcile=True)

    for role_name, spec in catalogue.items():
        assert _held_by(seeded_tenant.id, role_name) == set(spec["permissions"])


def test_reconciling_leaves_a_role_the_school_made_alone(
    flask_app, db_session, seeded_tenant
):
    """The catalogue describes the four default roles and nothing else.

    A school that built its own role — an Exams Officer, a Cashier — has made a
    decision the seeder knows nothing about, and must not have it emptied.
    """
    from modules.rbac.models import Role
    from modules.rbac.role_seeder import seed_roles_for_tenant

    suffix = uuid.uuid4().hex[:8]
    own = Role(
        id=f"r-{suffix}",
        tenant_id=seeded_tenant.id,
        name=f"Exams Officer {suffix}",
        description="Built by the school",
    )
    db_session.add(own)
    db_session.flush()
    _grant_extra(db_session, seeded_tenant.id, own.name, "zz.their.own.key")

    with flask_app.test_request_context("/"):
        seed_roles_for_tenant(seeded_tenant.id, reconcile=True)

    assert "zz.their.own.key" in _held_by(seeded_tenant.id, own.name)
