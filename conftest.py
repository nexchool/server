"""Root-level pytest conftest.

Two responsibilities:
  1. Put the server directory on sys.path so tests outside tests/ (e.g.
     modules/<x>/tests/...) can `import modules.foo`.
  2. Re-export the shared fixtures (flask_app, db_session, tenant, student, ...)
     defined in tests/conftest.py so they're discoverable from any test root.

This keeps existing tests/ behaviour identical while letting per-module test
trees share the same Flask app and transactional DB session.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/school_erp",
)

# Re-export the shared fixtures defined in tests/conftest.py.
# Tests under modules/<x>/tests/ aren't descendants of tests/, so pytest
# would not normally pick that conftest up — pull the fixtures up here.
#
# Autouse fixtures have to be named here too. They apply to everything below
# the conftest that *defines* them, and a module test tree is not below
# tests/ — so `_no_outbound_delivery` was silently inactive for every test
# under modules/, which is how the student-leave suite came to spend twenty
# seconds per test retrying a broker connection.
from tests.conftest import (  # noqa: F401,E402
    flask_app,
    _db_engine,
    db_session,
    _no_outbound_delivery,
    tenant,
    hostel,
    room,
    bed,
    beds,
    student,
    student2,
)
