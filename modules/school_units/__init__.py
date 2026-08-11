"""
School Units Module

Sub-schools / campuses inside a tenant (e.g. "Modi Primary",
"Modi Higher Secondary"). One tenant can have many SchoolUnits.

The whole HTTP surface is GraphQL, under the v2 name for these — a campus:
`campuses` to read, `addCampus` / `updateCampus` / `removeCampus` to change.
There is no REST blueprint.
"""

from . import models  # noqa: E402, F401
