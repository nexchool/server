"""Build the People model from existing v1 data.

Usage:

    python scripts/backfill_people.py --dry-run            # every tenant, rolled back
    python scripts/backfill_people.py --tenant acme        # one tenant, committed
    python scripts/backfill_people.py --report out.json    # keep the suggestions

Safe to run repeatedly: a second run over the same data changes nothing.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

logger = logging.getLogger("backfill_people")


def _resolve_tenants(identifier: str | None) -> list:
    from core.models import Tenant

    if not identifier:
        return Tenant.query.all()

    tenant = Tenant.query.filter_by(subdomain=identifier).first() or Tenant.query.get(
        identifier
    )
    if tenant is None:
        raise SystemExit(f"No tenant matches '{identifier}'")
    return [tenant]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", help="Tenant id or subdomain. Omit for all tenants.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Roll back instead of committing, to rehearse the run.",
    )
    parser.add_argument("--report", help="Write the suggestions to this JSON file.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from app import create_app
    from core.database import db
    from modules.people.backfill import backfill_tenant

    app = create_app()
    with app.app_context():
        tenants = _resolve_tenants(args.tenant)
        reports = []

        for tenant in tenants:
            report = backfill_tenant(tenant.id)
            reports.append(report)
            logger.info("%s %s", tenant.subdomain, report.summary())

        if args.dry_run:
            db.session.rollback()
            logger.info("Dry run — everything rolled back.")
        else:
            db.session.commit()
            logger.info("Committed.")

        if args.report:
            payload = [
                {"tenant_id": report.tenant_id, "suggestions": report.suggestions}
                for report in reports
            ]
            Path(args.report).write_text(json.dumps(payload, indent=2))
            logger.info("Suggestions written to %s", args.report)

        total_suggestions = sum(len(report.suggestions) for report in reports)
        if total_suggestions:
            logger.info(
                "%s suggestion(s) need a human decision; nothing was merged on them.",
                total_suggestions,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
