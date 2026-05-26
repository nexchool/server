"""
Eagerly import every modules/*/models.py so SQLAlchemy can resolve all
relationship strings (e.g. AcademicProgramme -> "Medium" -> "Class").

Some tests construct ORM instances directly; constructing a single model
triggers SQLAlchemy's lazy `_configure_registries`, which fails if any peer
mapper references an unimported class by string name. Importing every model
module up-front avoids that order-dependent failure.

Usage in test files:

    from tests._model_loader import load_all_models
    load_all_models()
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

_LOADED = False


def load_all_models() -> None:
    """Import every modules/*/models.py and modules/*/*/models.py once."""
    global _LOADED
    if _LOADED:
        return

    server_dir = Path(__file__).resolve().parent.parent
    modules_root = server_dir / "modules"

    for path in modules_root.rglob("models.py"):
        # Convert filesystem path to dotted module name relative to server_dir.
        rel = path.relative_to(server_dir).with_suffix("")
        dotted = ".".join(rel.parts)
        try:
            importlib.import_module(dotted)
        except Exception:  # pragma: no cover - defensive: skip unimportable modules
            # If a single module fails to import we keep going; tests that
            # actually need that mapper will surface the real error.
            pass

    # Walk packages too, in case nested __init__.py shadows top-level discovery.
    for finder, name, _ in pkgutil.walk_packages([str(modules_root)], prefix="modules."):
        if name.endswith(".models"):
            try:
                importlib.import_module(name)
            except Exception:  # pragma: no cover
                pass

    _LOADED = True
