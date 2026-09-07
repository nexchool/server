"""Where a provider's secret lives, which is not in the database.

The repository stores every credential it has as an environment variable read
at start-up, and has no encryption at rest, no key management and no secret
store. Phase 3 does not invent one, and specifically does not invent the thing
that would be convenient — a plaintext credential column on a tenant's
integration row.

So the split is:

**Configuration metadata** — a sender id, a route, a base URL. Stored on the
tenant's integration, returned by APIs, safe in a log.

**Secret material** — an API key, a token. Never stored, never returned, never
logged. The database holds a *reference*: the name of the environment variable
the value lives in. Reading a `tenant_integrations` row tells you which
credential is in use and tells you nothing about what it is.

That reference costs almost nothing and buys the property that matters: a
database dump contains no provider secrets, and neither does an API response
that forgot to redact one, because there is nothing there to redact.

When a school one day brings its own vendor account and the secret genuinely
has to be per-tenant, this is the seam to change — and that change is envelope
encryption with a managed key, not a column. Deliberately not done here: it
would be the first secret in this repository to live in the database at all,
and it is not needed to select a provider.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

#: What a reference has to look like. Uppercase and underscores, the shape of
#: an environment variable — so a reference cannot be a value that somebody
#: pasted into the wrong field and nobody noticed.
import re

REFERENCE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


def is_valid_reference(reference: str) -> bool:
    return bool(reference and REFERENCE_PATTERN.match(reference))


def resolve_secret(reference: Optional[str]) -> Optional[str]:
    """The secret this reference names, or None.

    The only function in the codebase that turns a stored reference into a
    real credential. It returns the value to the caller that is about to use
    it and nowhere else — nothing here logs it, caches it, or puts it in a
    result.
    """
    if not reference or not is_valid_reference(reference):
        return None
    value = os.environ.get(reference)
    return value or None


def credentials_present(references: Dict[str, Optional[str]]) -> bool:
    """Whether every credential a provider needs is actually set.

    Answers the health question — "is this configured?" — without ever
    revealing, returning or logging a value. The caller learns yes or no.
    """
    if not references:
        return True
    return all(resolve_secret(reference) for reference in references.values())


def describe_references(references: Dict[str, Optional[str]]) -> Dict[str, Dict]:
    """What an operator may see about credentials: the names, and whether set.

    Never the values, and there is no parameter or branch here that could
    produce one.
    """
    return {
        purpose: {
            "reference": reference,
            "is_set": bool(resolve_secret(reference)),
        }
        for purpose, reference in (references or {}).items()
    }
