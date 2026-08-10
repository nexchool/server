"""
Grades Module

Master list of standards / grades a tenant offers (LKG, UKG, 1..12).
Classes reference a Grade rather than carrying free-text grade names so
the same grade can be reused across programmes.

The whole HTTP surface is GraphQL: `grades` to read, `addGrade` /
`updateGrade` / `removeGrade` to change. There is no REST blueprint.
"""

from . import models  # noqa: E402, F401
