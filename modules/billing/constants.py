"""The vocabulary of platform billing.

One file so that a price mode, a currency or a unit is spelled the same way in
the model, the calculation and the API — the previous arrangement had "INR"
written out as a literal in two functions that were meant to agree.
"""

from __future__ import annotations

#: NexSchool bills Indian schools in rupees. A currency column would be a
#: product decision (multi-currency pricing, FX, rounding rules) that nobody
#: has taken; until somebody does, this is the one place the answer lives
#: rather than two string literals that could drift.
DEFAULT_CURRENCY = "INR"

# --- how a school is charged for a service ----------------------------------
#
# Deliberately three, not a rule engine. Each one answers "what does the
# school pay?" from a different input, and a fourth would need a product
# reason nobody has given yet.

#: quantity × the school's unit price. An SMS bundle.
PRICING_METERED = "metered"
#: a flat annual amount whatever the usage. A support retainer.
PRICING_FIXED = "fixed"
#: the school pays what the provider charged, no margin. Cost recovery.
PRICING_PASS_THROUGH = "pass_through"

PRICING_MODES = (PRICING_METERED, PRICING_FIXED, PRICING_PASS_THROUGH)

# --- what an estimate is standing on -----------------------------------------
#
# An estimate that cannot say where its number came from invites being read as
# a bill. These say it out loud, and travel with every estimate.

#: an operator told us how much this school expects to use in a year
ESTIMATE_BASIS_CONFIGURED = "configured"
#: nobody told us, so we annualised what has actually been recorded
ESTIMATE_BASIS_OBSERVED = "observed"
#: no configured figure and nothing recorded — the honest answer is zero
ESTIMATE_BASIS_NONE = "none"

#: A billing component that is the NexSchool subscription itself, as opposed
#: to a third-party service. Kept as a key so a reader of a component list
#: does not have to recognise it by its label.
COMPONENT_SUBSCRIPTION = "subscription"
