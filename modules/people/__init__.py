"""People domain — the humans a school knows and how they are related.

Owns Person, the Staff relationship, Family and family participation. Other
domains reference these concepts; none of them redefine or duplicate identity.
"""

from .employment import Staff, StaffEmploymentPeriod
from .models import Family, FamilyMember, Person

__all__ = [
    "Person",
    "Family",
    "FamilyMember",
    "Staff",
    "StaffEmploymentPeriod",
]
