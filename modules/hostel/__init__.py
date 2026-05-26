"""Hostel module — facilities, allocations, visitors, gatepasses."""

from flask import Blueprint

hostel_bp = Blueprint("hostel", __name__, url_prefix="/hostel")

# Models
from modules.hostel.models import (  # noqa: E402, F401
    Hostel,
    HostelRoom,
    HostelBed,
    HostelAllocation,
    HostelVisitor,
    HostelVisitorLog,
    HostelGatepass,
    HostelGatepassAudit,
)

# Routes must be imported after `hostel_bp` so decorators can register.
from modules.hostel import routes  # noqa: E402, F401

__all__ = [
    "hostel_bp",
    "Hostel",
    "HostelRoom",
    "HostelBed",
    "HostelAllocation",
    "HostelVisitor",
    "HostelVisitorLog",
    "HostelGatepass",
    "HostelGatepassAudit",
]
