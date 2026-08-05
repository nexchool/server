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
    employments_created: int = 0
    platform_admins: int = 0
    # Students whose assignment is redundant because the relationship implies it.
    students_covered_by_implication: int = 0
    # Students whose assignment grants more than the relationship implies —
    # these must be answered before user_roles can be dropped.
    students_not_covered: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"tenant={self.tenant_id} moved={self.moved} "
            f"already={self.already_held} employed={self.employments_created} "
            f"students_covered={self.students_covered_by_implication} "
            f"students_uncovered={len(self.students_not_covered)} "
            f"platform_admins={self.platform_admins}"
        )


def _implied_access_covers(account, role_id: str) -> bool:
    """Whether the relationship already implies everything this role grants.

    The gate for dropping a student's assignment: if the relationship implies
    it, removing the row changes nothing. If it grants more, removing it would
    quietly take access away, and that must be decided rather than assumed.
    """
    from modules.rbac.authority_service import permission_keys_for_person
    from modules.rbac.models import Role

    role = Role.query.get(role_id)
    if role is None:
        return True

    granted = {permission.name for permission in role.permissions}
    implied = set(permission_keys_for_person(account.person_id))
    return granted.issubset(implied)


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

        if employment is None and account.person_id in student_person_ids:
            # A student holds no organizational authority. Their access follows
            # from being a student, so it is implied by the relationship and
            # this assignment is redundant — verified below before anything is
            # dropped.
            if _implied_access_covers(account, assignment.role_id):
                report.students_covered_by_implication += 1
            else:
                report.students_not_covered.append(
                    {"user_id": account.id, "email": account.email}
                )
            continue

        if employment is None:
            # An account holding authority with nothing to hold it: created
            # before employment was recorded at creation. They work here, so
            # record that, exactly as the People backfill does.
            from modules.people.service import employ

            employment = employ(tenant_id, account.person_id)
            employment_by_person[account.person_id] = employment
            report.employments_created += 1

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
            if report.moved or report.employments_created or report.students_not_covered:
                logger.info("%s %s", tenant.subdomain, report.summary())

        if args.dry_run:
            db.session.rollback()
            logger.info("Dry run — everything rolled back.")
        else:
            db.session.commit()
            logger.info("Committed.")

        blocked = defaultdict(int)
        for report in reports:
            blocked["students_covered"] += report.students_covered_by_implication
            blocked["students_uncovered"] += len(report.students_not_covered)
            blocked["employed"] += report.employments_created

        logger.info(
            "\n%s account(s) holding authority with no employment were employed.\n"
            "%s student assignment(s) are redundant: the relationship already "
            "implies everything they grant.",
            blocked["employed"],
            blocked["students_covered"],
        )
        if blocked["students_uncovered"]:
            logger.info(
                "%s student assignment(s) grant MORE than the relationship "
                "implies. Answer these before dropping user_roles.",
                blocked["students_uncovered"],
            )
        else:
            logger.info("Nothing now blocks retiring user_roles.")

        if args.report:
            Path(args.report).write_text(
                json.dumps(
                    [
                        {
                            "tenant_id": r.tenant_id,
                            "students_not_covered": r.students_not_covered,
                        }
                        for r in reports
                        if r.students_not_covered
                    ],
                    indent=2,
                )
            )
            logger.info("Unresolved holders written to %s", args.report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
