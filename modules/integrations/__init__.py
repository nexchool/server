"""Calling other people's services, without the rest of the codebase knowing who.

A feature asks for a **capability** — "send an SMS" — and this module decides
which vendor carries it for that school, calls it with a timeout, normalizes
whatever comes back, and records that it happened so billing can price it.

Not to be confused with `modules/billing`, which holds the same vendors'
*commercial* records. That module knows what a message costs; this one knows
how to send it. Neither holds the other's business.
"""
