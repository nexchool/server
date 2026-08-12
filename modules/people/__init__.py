"""People domain — the humans a school knows and how they are related.

Owns Person, the Staff relationship, Family and family participation. Other
domains reference these concepts; none of them redefine or duplicate identity.
"""

from .employment import Staff, StaffEmploymentPeriod
from .models import Family, FamilyMember, Person

# Importing the service registers the guarantee that every account has a person.
from . import service  # noqa: F401  (import for side effect)

# Registers "person" with the document store. Registration happens on import,
# so a domain whose catalogue is never imported has no owner kind.
from . import document_catalog  # noqa: F401  (import for side effect)

__all__ = [
    "Person",
    "Family",
    "FamilyMember",
    "Staff",
    "StaffEmploymentPeriod",
]
