"""Batching the reads a page fans out into.

A GraphQL field is resolved per object, so a hundred students each asking
for their class is a hundred queries unless something collects them.

The usual answer is an async DataLoader that gathers keys within a tick.
This application is synchronous — WSGI, sync SQLAlchemy — so there is no
tick to gather in, and an async loader here would only mean an event loop
started to do blocking work. The synchronous equivalent is to fetch what a
page will ask for at the moment the page is known, and let each field read
the answer: one query either way, no machinery pretending to be concurrent.

One set per request. Two requests must never share these — the cache holds
one tenant's rows, and it is scoped to the question being answered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional


class ClassLoader:
    """Classes this request has already looked up, and how to fill it."""

    def __init__(self) -> None:
        self._known: Dict[str, Any] = {}

    def prime(self, class_ids: Iterable[str]) -> None:
        """Fetch, in one query, every class the page is about to ask for."""
        from modules.students.services import classes_by_id

        missing = {cid for cid in class_ids if cid and cid not in self._known}
        if not missing:
            return
        found = classes_by_id(missing)
        for class_id in missing:
            # Misses are remembered too, so a class that does not exist is
            # not looked up once per student that points at it.
            self._known[class_id] = found.get(class_id)

    def get(self, class_id: Optional[str]) -> Optional[Any]:
        """The class, priming it alone if the caller never primed a page."""
        if not class_id:
            return None
        if class_id not in self._known:
            self.prime([class_id])
        return self._known.get(class_id)


@dataclass
class Loaders:
    """The batched reads available to this request's resolvers."""

    classes: ClassLoader = field(default_factory=ClassLoader)


def build_loaders() -> Loaders:
    return Loaders()
