"""Pure-Python tests for school_setup support models."""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from tests._model_loader import load_all_models  # noqa: E402

load_all_models()


def test_setup_module_event_repr():
    from modules.school_setup.models import SetupModuleEvent

    event = SetupModuleEvent(tenant_id="t1", module="units", event="completed")
    rendered = repr(event)
    assert "units:completed" in rendered
    assert "t1" in rendered


def test_data_purge_log_can_be_constructed():
    from modules.school_setup.models import DataPurgeLog

    purge = DataPurgeLog(tenant_id="t1", data_type="audit_logs", records_deleted=42)
    assert purge.tenant_id == "t1"
    assert purge.data_type == "audit_logs"
    assert purge.records_deleted == 42
