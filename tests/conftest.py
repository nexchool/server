"""Shared pytest fixtures for service / route tests.

Strategy
========

For tests that need a real database (services, routes, integration), we
use the existing PostgreSQL `school_erp` database with **savepoint
transactions** so each test rolls back its changes:

    1. fixture `db_session` opens a connection + outer transaction.
    2. SQLAlchemy session is bound to that connection with a SAVEPOINT.
    3. Each test runs inside the savepoint; on teardown we ROLLBACK.

This gives full PostgreSQL fidelity (partial unique indexes, CHECK
constraints, FK cascades, generated SQL types) without polluting data.

Pure-Python model tests (test_hostel_models.py etc.) do not need this
fixture; they continue to use `tests._model_loader.load_all_models()`.

The fixture is **session-scoped** for the Flask app (single instance reused)
but **function-scoped** for the database session (clean state per test).

Connection requires DATABASE_URL pointing at a running postgres
(`postgresql://postgres:postgres@localhost:5432/school_erp` for local dev).
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# Default to local postgres if DATABASE_URL not set. Tests can be skipped
# entirely by setting NO_DB=1 in the environment (useful in CI without
# postgres available).
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/school_erp",
)


# ---------------------------------------------------------------------------
# Flask app — session-scoped
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def flask_app():
    """Reuse a single Flask app across the session."""
    from app import app as _app
    _app.config["TESTING"] = True
    return _app


@pytest.fixture(scope="session")
def _db_engine(flask_app):
    """Bind to the real SQLAlchemy engine from the app."""
    from core.database import db
    with flask_app.app_context():
        yield db.engine


# ---------------------------------------------------------------------------
# Per-test database session with rollback
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session(flask_app, _db_engine):
    """Provide a SQLAlchemy session whose changes are rolled back after the test.

    Yields the global `db.session` proxy; this works because we replace
    its bind with our transactional connection and override the session
    factory for the duration of the test. Standard pattern for Flask-SQLAlchemy.
    """
    from core.database import db

    with flask_app.app_context():
        connection = _db_engine.connect()
        outer_transaction = connection.begin()

        # Bind the session to the test connection so all queries see
        # the in-progress (uncommitted) state.
        original_bind = db.session.get_bind()
        db.session.remove()
        db.session.configure(bind=connection)

        try:
            yield db.session
        finally:
            # Roll back everything the test did.
            db.session.close()
            outer_transaction.rollback()
            connection.close()
            # Restore the original bind so other tests / fixtures aren't
            # left with a closed connection.
            db.session.configure(bind=original_bind)


# ---------------------------------------------------------------------------
# Helper fixtures: tenant, student, hostel, room, bed
# ---------------------------------------------------------------------------

def _new_id(prefix: str = "") -> str:
    """Return a short test-scoped ID prefix for readable failures."""
    return f"{prefix}{uuid.uuid4().hex[:12]}" if prefix else str(uuid.uuid4())


@pytest.fixture
def tenant(db_session):
    """Create an active tenant for tenant-scoped tests."""
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    t = Tenant(
        id=_new_id("t-"),
        name="Test School",
        subdomain=f"test-{uuid.uuid4().hex[:6]}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(t)
    db_session.flush()
    return t


@pytest.fixture
def hostel(db_session, tenant):
    """Create an active hostel with capacity 20."""
    from modules.hostel.models import Hostel

    h = Hostel(
        id=_new_id("h-"),
        tenant_id=tenant.id,
        name="Boys Hostel A",
        capacity=20,
    )
    db_session.add(h)
    db_session.flush()
    return h


@pytest.fixture
def room(db_session, tenant, hostel):
    """Create a room with capacity 4 in the hostel."""
    from modules.hostel.models import HostelRoom

    r = HostelRoom(
        id=_new_id("r-"),
        tenant_id=tenant.id,
        hostel_id=hostel.id,
        room_number="101",
        capacity=4,
    )
    db_session.add(r)
    db_session.flush()
    return r


@pytest.fixture
def bed(db_session, tenant, room):
    """Create one bed in the room."""
    from modules.hostel.models import HostelBed

    b = HostelBed(
        id=_new_id("b-"),
        tenant_id=tenant.id,
        room_id=room.id,
        bed_number="A1",
    )
    db_session.add(b)
    db_session.flush()
    return b


@pytest.fixture
def beds(db_session, tenant, room):
    """Create 4 beds (A1..A4) in the room. Returns a list."""
    from modules.hostel.models import HostelBed

    created = []
    for i in range(1, 5):
        b = HostelBed(
            id=_new_id("b-"),
            tenant_id=tenant.id,
            room_id=room.id,
            bed_number=f"A{i}",
        )
        db_session.add(b)
        created.append(b)
    db_session.flush()
    return created


def _make_student(db_session, tenant, *, name: str, admission_suffix: str):
    """Create a (User, Student) pair. Student rows depend on a User row."""
    from modules.auth.models import User
    from modules.students.models import Student

    user = User(
        id=_new_id("u-"),
        tenant_id=tenant.id,
        email=f"{admission_suffix}@test.school",
        password_hash="x" * 60,  # dummy hash; not exercised by hostel tests
        name=name,
    )
    db_session.add(user)
    db_session.flush()

    student = Student(
        id=_new_id("s-"),
        tenant_id=tenant.id,
        user_id=user.id,
        admission_number=f"ADM-{admission_suffix}",
    )
    db_session.add(student)
    db_session.flush()
    return student


@pytest.fixture
def student(db_session, tenant):
    """Create a Student (and its backing User)."""
    return _make_student(
        db_session,
        tenant,
        name="Rajesh Kumar",
        admission_suffix=uuid.uuid4().hex[:8],
    )


@pytest.fixture
def student2(db_session, tenant):
    """Create a second Student (and its backing User) for multi-student tests."""
    return _make_student(
        db_session,
        tenant,
        name="Amit Singh",
        admission_suffix=uuid.uuid4().hex[:8],
    )
