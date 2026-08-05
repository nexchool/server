"""Move account-held roles onto the employments that should hold them (ADR-013).

    python scripts/backfill_authority.py --dry-run
    python scripts/backfill_authority.py --tenant acme

Additive and idempotent: nothing is removed from ``user_roles``. Permission
resolution reads both sources, so this changes no one's access — it only puts
authority where it belongs so the account-held half can be retired later.

The report is the point. It names every holder whose authority *cannot* move to
an employment, because those are the cases that must be answered before
``user_roles`` can be dropped:

  - students, who hold no employment and never will
  - accounts with no business relationship at all
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

logger = logging.getLogger("backfill_authority")


@dataclass
class AuthorityReport:
    tenant_id: str
    moved: int = 0
    already_held: int = 0
    # Holders whose authority cannot live on an employment.
    students: int = 0
    platform_admins: int = 0
    without_relationship: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"tenant={self.tenant_id} moved={self.moved} "
            f"already={self.already_held} students={self.students} "
            f"platform_admins={self.platform_admins} "
            f"no_relationship={len(self.without_relationship)}"
        )


def _move_tenant_authority(tenant_id: str) -> AuthorityReport:
    from core.database import db
    from modules.auth.models import User
    from modules.people.employment import Staff
    from modules.rbac.models import StaffAuthority, UserRole
    from modules.students.models import Student

    report = AuthorityReport(tenant_id=tenant_id)

    accounts = {
        user.id: user for user in User.query.filter(User.tenant_id == tenant_id).all()
    }
    employment_by_person = {
        staff.person_id: staff
        for staff in Staff.query.filter(Staff.tenant_id == tenant_id).all()
    }
    student_person_ids = {
        student.person_id
        for student in Student.query.filter(Student.tenant_id == tenant_id).all()
    }
    already = {
        (held.staff_id, held.role_id)
        for held in StaffAuthority.query.filter(
            StaffAuthority.tenant_id == tenant_id
        ).all()
    }

    for assignment in UserRole.query.filter(UserRole.tenant_id == tenant_id).all():
        account = accounts.get(assignment.user_id)
        if account is None:
            continue

        if account.is_platform_admin:
            # Platform administrators run Nexchool and bypass tenant
            # authorization entirely; they are not employed by the school.
            report.platform_admins += 1
            continue

        employment = employment_by_person.get(account.person_id)
        if employment is None:
            if account.person_id in student_person_ids:
                # A student holds no organizational authority. Their access
                # follows from being a student, which is a different thing.
                report.students += 1
            else:
                report.without_relationship.append(
                    {"user_id": account.id, "email": account.email}
                )
            continue

        if (employment.id, assignment.role_id) in already:
            report.already_held += 1
            continue

        db.session.add(
            StaffAuthority(
                tenant_id=tenant_id,
                staff_id=employment.id,
                role_id=assignment.role_id,
            )
        )
        already.add((employment.id, assignment.role_id))
        report.moved += 1

    db.session.flush()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", help="Tenant id or subdomain. Omit for all.")
    parser.add_argument("--dry-run", action="store_true", help="Roll back instead of committing.")
    parser.add_argument("--report", help="Write the unmovable holders to this JSON file.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from app import create_app
    from core.database import db
    from core.models import Tenant

    app = create_app()
    with app.app_context():
        if args.tenant:
            tenant = Tenant.query.filter_by(subdomain=args.tenant).first() or Tenant.query.get(args.tenant)
            if tenant is None:
                raise SystemExit(f"No tenant matches '{args.tenant}'")
            tenants = [tenant]
        else:
            tenants = Tenant.query.all()

        reports = [_move_tenant_authority(t.id) for t in tenants]
        for tenant, report in zip(tenants, reports):
            if report.moved or report.without_relationship:
                logger.info("%s %s", tenant.subdomain, report.summary())

        if args.dry_run:
            db.session.rollback()
            logger.info("Dry run — everything rolled back.")
        else:
            db.session.commit()
            logger.info("Committed.")

        blocked = defaultdict(int)
        for report in reports:
            blocked["students"] += report.students
            blocked["accounts_without_a_relationship"] += len(report.without_relationship)

        logger.info(
            "\nBefore user_roles can be dropped:\n"
            "  %s student assignment(s) need student access to be implied by the "
            "Student relationship rather than granted.\n"
            "  %s account(s) hold roles but have no business relationship to hold "
            "authority — each needs one, or needs to stop holding authority.",
            blocked["students"],
            blocked["accounts_without_a_relationship"],
        )

        if args.report:
            Path(args.report).write_text(
                json.dumps(
                    [
                        {
                            "tenant_id": r.tenant_id,
                            "accounts_without_a_relationship": r.without_relationship,
                        }
                        for r in reports
                        if r.without_relationship
                    ],
                    indent=2,
                )
            )
            logger.info("Unmovable holders written to %s", args.report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
