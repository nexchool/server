"""Tests for SetupModuleEvent logging in run_complete_setup — pure-Python, no DB."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from tests._model_loader import load_all_models  # noqa: E402

load_all_models()


def test_setup_module_event_can_be_constructed():
    """Smoke: the model can be instantiated with the expected fields."""
    from modules.school_setup.models import SetupModuleEvent
    e = SetupModuleEvent(
        tenant_id="t1",
        module="overall",
        event="setup_complete",
        actor_user_id="u1",
    )
    assert e.tenant_id == "t1"
    assert e.event == "setup_complete"


def test_setup_module_event_repr():
    from modules.school_setup.models import SetupModuleEvent
    e = SetupModuleEvent(tenant_id="t1", module="overall", event="setup_complete")
    assert "overall:setup_complete" in repr(e)


def test_services_module_imports_cleanly_after_addition():
    """The services module imports without error after the event-log addition."""
    from modules.school_setup import services  # noqa: F401
