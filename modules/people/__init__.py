"""People domain — the humans a school knows and how they are related.

Owns Person, Family and family participation. Other domains reference these
concepts; none of them redefine or duplicate identity.
"""

from .models import Family, FamilyMember, Person

__all__ = ["Person", "Family", "FamilyMember"]
