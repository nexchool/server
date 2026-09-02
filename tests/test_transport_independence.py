"""Business logic exists once, and neither transport is built on the other.

    REST     → Service → Repository
    GraphQL  → Service → Repository

GraphQL is being introduced without replacing REST, which is only safe while
both are thin. The moment one calls the other, there are two answers to
maintain and the newer transport inherits the older one's shape — which is how
a second API becomes a permanent proxy instead of a replacement.

Checked by reading imports, not by exercising behaviour: a boundary that holds
only because nobody has crossed it yet is not a boundary.
"""

from __future__ import annotations

import ast
import pathlib

SERVER = pathlib.Path(__file__).resolve().parents[1]

# Anything that would let one transport reach the other over HTTP rather than
# calling the service both are supposed to share.
HTTP_CLIENTS = {"requests", "httpx", "urllib.request", "urllib3", "aiohttp"}

GRAPHQL_PATHS = [SERVER / "graphql_api"]
GRAPHQL_PATHS += list(SERVER.glob("modules/*/graphql"))
GRAPHQL_PATHS += list(SERVER.glob("modules/*/resolvers.py"))


def _python_files(paths):
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            yield path
        elif path.is_dir():
            yield from path.rglob("*.py")


def _imports(source: str):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name


def test_graphql_does_not_call_rest():
    """A resolver reaching for an HTTP client is reaching for our own API."""
    offenders = []

    for path in _python_files(GRAPHQL_PATHS):
        for module in _imports(path.read_text()):
            if module.split(".")[0] in {m.split(".")[0] for m in HTTP_CLIENTS}:
                offenders.append(f"{path.relative_to(SERVER)} imports {module}")

    assert not offenders, (
        "GraphQL must call services, not our own REST endpoints:\n  "
        + "\n  ".join(offenders)
    )


def test_rest_does_not_call_graphql():
    """The reverse, which would make REST a client of the newer transport."""
    offenders = []

    for path in SERVER.glob("modules/*/routes.py"):
        source = path.read_text()
        for module in _imports(source):
            if "graphql" in module and "graphql_api.errors" not in module:
                offenders.append(f"{path.relative_to(SERVER)} imports {module}")
        if "/api/graphql" in source:
            offenders.append(f"{path.relative_to(SERVER)} references the GraphQL endpoint")

    assert not offenders, (
        "REST must not depend on GraphQL:\n  " + "\n  ".join(offenders)
    )


def test_resolvers_do_not_query_the_database():
    """A resolver composes a service's answer; it does not fetch its own.

    Querying from a resolver puts the business rule in a second place, and the
    two disagree the first time either is changed. Naming a model — a status
    constant, a type annotation — is fine; running a query is not.
    """
    offenders = []

    for path in _python_files(GRAPHQL_PATHS):
        source = path.read_text()
        for marker in (".query.", "db.session", "session.execute"):
            if marker in source:
                offenders.append(f"{path.relative_to(SERVER)} uses {marker}")

    assert not offenders, (
        "GraphQL must ask a service rather than query for itself:\n  "
        + "\n  ".join(offenders)
    )


def test_the_only_orm_hooks_enforce_consistency():
    """ORM events may keep records consistent. They may not run business.

    Employing somebody, admitting a child, granting authority — those are
    events a reader must be able to find in a service. An ORM hook is the
    wrong place to learn that the organization hired someone.

    This pins the list, so adding a hook is a deliberate act that has to be
    argued for here rather than a quiet one.
    """
    allowed = {
        # An account belongs to a person. Enforced centrally because a dozen
        # places open accounts and "remember the person too" is a rule that
        # will eventually be forgotten — the same argument as tenant scoping.
        ("modules/auth/person_link.py", "before_flush"),
        # Every tenant-scoped read is scoped. The guarantee the whole product
        # rests on; it cannot be left to each query to remember.
        ("core/database.py", "do_orm_execute"),
        # A cached permission set stops agreeing with the employment it was
        # derived from the moment that employment's standing changes. Keeping
        # a derived value in step with its source is consistency, not
        # workflow: nothing is decided here and no business event happens —
        # suspending someone is still `record_employment_standing`, which a
        # reader can find. Employment status is written from several paths,
        # and the one that forgets is the one that leaves a suspended
        # employee able to act.
        ("modules/rbac/authority_service.py", "after_flush"),
        # A class, term or calendar that names an academic year also names the
        # cycle inside it, and `academic_cycle_id` is NOT NULL. While a year
        # has one main cycle — every year until a school opens a second — the
        # value is derivable from the year alone, so filling it in is
        # consistency rather than workflow: nothing is decided and no business
        # event happens. Opening a cycle is `ensure_default_cycle`, which a
        # reader can find. Ten production writers and several dozen fixtures
        # build these rows; the one that forgets is the one that fails at
        # insert.
        ("modules/academics/cycles/consistency.py", "before_flush"),
        # The moment a permission invalidation is allowed to take effect.
        # Clearing the cache before the commit is a race: the row still reads
        # as it did, so a concurrent request reloads the *old* permissions and
        # caches them again — for the full TTL, with the revocation already
        # applied underneath. These two hold the invalidation until the
        # transaction is visible, and throw it away if it rolls back.
        #
        # Consistency, not workflow, and narrowly so: nothing is decided here.
        # Whoever called `invalidate_user_permissions` already decided —
        # `withdraw_authority`, `suspend_sub_admin`, `remove_login_for_deleted_
        # profile` — and a reader finds the decision there. All these do is
        # choose the instant at which a derived value stops being wrong.
        ("modules/rbac/services.py", "after_commit"),
        ("modules/rbac/services.py", "after_rollback"),
    }

    found = set()
    for path in list(SERVER.glob("modules/**/*.py")) + list(SERVER.glob("core/*.py")):
        if "test" in str(path) or "/venv/" in str(path):
            continue
        source = path.read_text()
        for hook in (
            "before_flush", "after_flush", "before_insert", "after_insert",
            "before_update", "after_update", "before_delete", "after_delete",
            "do_orm_execute", "before_commit", "after_commit",
        ):
            if f'"{hook}"' in source and ("event.listen" in source or "listens_for" in source):
                found.add((str(path.relative_to(SERVER)), hook))

    unexpected = found - allowed
    assert not unexpected, (
        "New ORM lifecycle hook(s). If this enforces consistency, add it to the "
        "allowed list with the reason. If it runs a business workflow, it "
        "belongs in a service where a reader can find it:\n  "
        + "\n  ".join(f"{where}: {hook}" for where, hook in sorted(unexpected))
    )
