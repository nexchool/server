"""
Academic Programmes Module

Board + optional medium of instruction (e.g. "CBSE", "GSEB Gujarati").
Classes reference exactly one programme so the same grade name can exist in
parallel across programmes inside a tenant.

The whole HTTP surface is GraphQL: `programmes` to read, `addProgramme` /
`updateProgramme` / `removeProgramme` to change. There is no REST blueprint.
"""

from . import models  # noqa: E402, F401
