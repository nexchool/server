"""What each seeded role is allowed to hold, and why.

Two things make role grants drift silently.

The first is that there are two definitions of the same four roles:
`scripts/seed_rbac.py` (the CLI) and `modules/rbac/role_seeder.py` (what runs
when a tenant is created and on every login). Nothing forces them to agree, and
a key added to one is simply absent from the other depending on how a tenant was
made.

The second is that `seed_roles_for_tenant` only ever adds. It backfills missing
permissions and never revokes one, so an over-grant survives every reseed and
can only be taken back by a migration. That makes an accidental grant permanent
in practice, which is why the ones below are asserted rather than reviewed.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

SERVER = pathlib.Path(__file__).resolve().parent.parent


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli_roles():
    return _load(SERVER / "scripts" / "seed_rbac.py", "_seed_rbac_roles").ROLES


@pytest.fixture(scope="module")
def runtime_roles():
    from modules.rbac.role_seeder import DEFAULT_ROLES

    return DEFAULT_ROLES


def _permissions(role_spec) -> set:
    return set(role_spec["permissions"])


def test_the_two_role_definitions_name_the_same_roles(cli_roles, runtime_roles):
    assert set(cli_roles) == set(runtime_roles)


@pytest.mark.parametrize("role", ["Admin", "Teacher", "Student", "Parent"])
def test_the_two_role_definitions_grant_the_same_keys(
    role, cli_roles, runtime_roles
):
    """A tenant's authority must not depend on which seeder created it.

    If this fails, decide which grant is correct and change both — do not
    relax the test. The two callers are `scripts/seed_rbac.py` for a fresh
    install and `seed_roles_for_tenant` for every tenant created since.
    """
    cli = _permissions(cli_roles[role])
    runtime = _permissions(runtime_roles[role])
    assert cli == runtime, (
        f"{role} differs between the seeders — "
        f"only in seed_rbac.py: {sorted(cli - runtime)}; "
        f"only in role_seeder.py: {sorted(runtime - cli)}"
    )


@pytest.mark.parametrize("seeder", ["cli", "runtime"])
def test_a_teacher_does_not_hold_the_schools_onboarding_authority(
    seeder, cli_roles, runtime_roles
):
    """Standing a school up is the platform operator's work, done in the panel.

    `school_setup.read` answers "how far has onboarding got" — not a question a
    teacher asks. It was granted only to let a teacher read the mediums and
    subject contexts; those reads now accept `class_subject.read`, which is the
    authority a teacher actually holds. See debt 33 and migration 103.
    """
    roles = cli_roles if seeder == "cli" else runtime_roles
    held = {k for k in _permissions(roles["Teacher"]) if k.startswith("school_setup")}
    assert held == set(), f"Teacher holds {sorted(held)}"


@pytest.mark.parametrize("seeder", ["cli", "runtime"])
def test_a_teacher_can_still_read_class_subject_configuration(
    seeder, cli_roles, runtime_roles
):
    """The other half of the change above.

    Removing the setup key is only correct because this one is present — the
    mediums and subject-context reads accept it. Losing it would take the
    medium and subject-context lists away from every teacher.
    """
    roles = cli_roles if seeder == "cli" else runtime_roles
    assert "class_subject.read" in _permissions(roles["Teacher"])


def test_the_reads_a_teacher_needs_accept_the_key_a_teacher_holds():
    """`class_subject.read` must appear in the guards, not just in the role.

    Asserted against the route modules rather than a live request because the
    pairing is what regresses: someone tightens a guard back to
    `class_subject.manage` and the teacher-facing list quietly 403s.
    """
    from modules.academics import resolvers as academics_resolvers
    from modules.mediums import routes as medium_routes
    from modules.subject_contexts import routes as context_routes

    assert medium_routes.PERM_CS_READ == "class_subject.read"
    assert context_routes.PERM_CS_READ == "class_subject.read"
    assert academics_resolvers.PERM_CLASS_SUBJECT_READ == "class_subject.read"

    for module in (medium_routes, context_routes):
        source = pathlib.Path(module.__file__).read_text()
        assert "PERM_CS_READ)" in source, (
            f"{module.__name__} defines the read key but no guard accepts it"
        )
