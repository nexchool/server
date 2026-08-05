"""Review and combine Person records that describe one human.

    python scripts/merge_people.py suggest --tenant acme
    python scripts/merge_people.py merge --keep <person-id> --absorb <person-id> \
        --reason "confirmed with the office"

Suggestions are questions, not decisions: a shared household phone looks exactly
like a duplicate and usually is not one. Read the names before merging.

Until the admin screen exists this is how a merge is performed.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

logger = logging.getLogger("merge_people")


def _tenant_for(identifier: str):
    from core.models import Tenant

    tenant = Tenant.query.filter_by(subdomain=identifier).first() or Tenant.query.get(
        identifier
    )
    if tenant is None:
        raise SystemExit(f"No tenant matches '{identifier}'")
    return tenant


def _suggest(args) -> int:
    from modules.people.merge import suggest_duplicates
    from modules.people.models import Person

    tenant = _tenant_for(args.tenant)
    suggestions = suggest_duplicates(tenant.id, limit=args.limit)

    if not suggestions:
        logger.info("Nothing looks duplicated in %s.", tenant.subdomain)
        return 0

    for suggestion in suggestions:
        first = Person.query.get(suggestion.person_id)
        second = Person.query.get(suggestion.other_person_id)
        logger.info(
            "%s (%s)  <->  %s (%s)\n    %s\n    merge --keep %s --absorb %s\n",
            first.full_name,
            first.phone_number or "no phone",
            second.full_name,
            second.phone_number or "no phone",
            suggestion.reason,
            first.id,
            second.id,
        )

    logger.info("%s suggestion(s). None of them merged anything.", len(suggestions))
    return 0


def _merge(args) -> int:
    from core.database import db
    from modules.people.merge import MergeRefused, merge_people

    try:
        record = merge_people(args.keep, args.absorb, reason=args.reason)
    except MergeRefused as refusal:
        logger.error("Refused: %s", refusal)
        return 1

    db.session.commit()
    logger.info(
        "Merged %s into %s. Recorded as %s, so it can be reviewed later.",
        args.absorb,
        args.keep,
        record.id,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    suggest = commands.add_parser("suggest", help="List people who look like duplicates.")
    suggest.add_argument("--tenant", required=True, help="Tenant id or subdomain.")
    suggest.add_argument("--limit", type=int, default=100)
    suggest.set_defaults(handler=_suggest)

    merge = commands.add_parser("merge", help="Combine two records into one person.")
    merge.add_argument("--keep", required=True, help="Person id that remains.")
    merge.add_argument("--absorb", required=True, help="Person id absorbed into it.")
    merge.add_argument("--reason", help="Why they were judged the same human.")
    merge.set_defaults(handler=_merge)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from app import create_app

    app = create_app()
    with app.app_context():
        return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
