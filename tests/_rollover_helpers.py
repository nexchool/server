"""
Shared test helpers for rollover service tests.

The rollover services use SQLAlchemy queries (`Model.query.filter(...).all()`).
We stub those by giving each model a ``query`` attribute backed by a small
chainable fake. Each fake has a queue of canned results; consecutive
``.all()`` / ``.first()`` / ``.count()`` calls pop from the queue in order.

This keeps the tests pure-Python (no DB, no Flask app) while still exercising
the real service code paths and decision logic.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List


class _QueryStub:
    """Chainable query stub that resolves terminals from a fixed queue."""

    def __init__(self, queue: List[Any]):
        # Each element is the result of one .all() / .first() / .count() call.
        self._queue = list(queue)
        self.calls: List[str] = []

    # Chainables — return self so chained .filter().filter_by()... works.
    def filter(self, *_a, **_kw):
        self.calls.append("filter")
        return self

    def filter_by(self, **_kw):
        self.calls.append("filter_by")
        return self

    def order_by(self, *_a, **_kw):
        self.calls.append("order_by")
        return self

    def offset(self, *_a, **_kw):
        self.calls.append("offset")
        return self

    def limit(self, *_a, **_kw):
        self.calls.append("limit")
        return self

    def join(self, *_a, **_kw):
        self.calls.append("join")
        return self

    def options(self, *_a, **_kw):
        self.calls.append("options")
        return self

    # Terminals.
    def all(self) -> Any:
        if not self._queue:
            return []
        item = self._queue.pop(0)
        return item if isinstance(item, list) else [item]

    def first(self):
        if not self._queue:
            return None
        item = self._queue.pop(0)
        if isinstance(item, list):
            return item[0] if item else None
        return item

    def count(self) -> int:
        if not self._queue:
            return 0
        item = self._queue.pop(0)
        if isinstance(item, int):
            return item
        if isinstance(item, list):
            return len(item)
        return 1 if item is not None else 0


class _AnyColumn:
    """Stand-in for a SQLAlchemy column attribute. Supports comparison
    operators and the SQL-builder methods our services use (``in_``, ``is_``,
    ``isnot``). Each operation just returns itself so it can be passed into
    ``.filter(...)`` calls without exploding."""

    def __eq__(self, _other): return self
    def __ne__(self, _other): return self
    def __lt__(self, _other): return self
    def __le__(self, _other): return self
    def __gt__(self, _other): return self
    def __ge__(self, _other): return self
    def __hash__(self): return id(self)
    def __bool__(self): return False
    def in_(self, *_a, **_kw): return self
    def is_(self, *_a, **_kw): return self
    def isnot(self, *_a, **_kw): return self
    def notin_(self, *_a, **_kw): return self
    def desc(self): return self
    def asc(self): return self


class _FakeModel:
    """Stand-in ORM model. ``.query`` returns the configured QueryStub;
    every other attribute returns a fresh _AnyColumn so that filter
    expressions like ``Model.tenant_id == 'x'`` evaluate without errors;
    calling the model as a constructor returns a SimpleNamespace populated
    with the kwargs (so ``db.session.add(Holiday(...))`` lands as a row in
    the FakeSession)."""

    def __init__(self, queue: List[Any]):
        self.query = _QueryStub(queue)

    def __getattr__(self, _name):
        return _AnyColumn()

    def __call__(self, **kwargs) -> SimpleNamespace:
        return SimpleNamespace(**kwargs)


def make_fake_model(queue: List[Any]) -> _FakeModel:
    """Return a stand-in 'model' object whose ``.query`` is a fresh QueryStub."""
    return _FakeModel(queue)


def install_fake_model(monkeypatch, module, attr_name: str, queue: List[Any]):
    """Replace ``module.attr_name`` with a stand-in model whose .query
    pops from the supplied queue. Returns the underlying _QueryStub so the
    test can inspect call history if desired."""
    fake_model = _FakeModel(queue)
    monkeypatch.setattr(module, attr_name, fake_model, raising=False)
    return fake_model.query


class FakeSession:
    """Records db.session interactions without touching a real DB."""

    def __init__(self, *, raise_on_commit: bool = False):
        self.added: List[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self._raise_on_commit = raise_on_commit

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        if self._raise_on_commit:
            raise RuntimeError("forced commit failure")
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def flush(self):
        self.flushes += 1


def install_fake_session(monkeypatch, module, *, raise_on_commit=False) -> FakeSession:
    """Patch the module's ``db`` symbol so ``db.session`` is the FakeSession."""
    sess = FakeSession(raise_on_commit=raise_on_commit)
    fake_db = SimpleNamespace(session=sess)
    monkeypatch.setattr(module, "db", fake_db, raising=True)
    return sess


def row(**kwargs) -> SimpleNamespace:
    """Tiny ORM-row stand-in that supports attribute access only."""
    return SimpleNamespace(**kwargs)
