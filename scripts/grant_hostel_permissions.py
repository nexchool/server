"""One-off script: ensure every existing Admin role has the hostel.* permissions.

The hostel module was added after roles were already seeded for live
tenants. The seed_rbac script is normally run on a fresh tenant —
re-running it on a live system needs tenant context.

This script:
  1. Creates each hostel.* Permission row if missing (global table).
  2. For every tenant's Admin role, attaches every hostel.* permission
     not already linked.

Idempotent — safe to run multiple times.

Run inside the api container:
    python scripts/grant_hostel_permissions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app import create_app  # noqa: E402

HOSTEL_PERMISSIONS = [
    ("hostel.read", "View hostels, rooms, and beds"),
    ("hostel.manage", "Create / update / delete hostels, rooms, and beds"),
    ("hostel.allocations.read", "View hostel allocations"),
    ("hostel.allocations.manage", "Allocate students to beds / check out"),
    ("hostel.visitors.read", "View hostel visitor logs"),
    ("hostel.visitors.manage", "Check hostel visitors in / out"),
    ("hostel.gatepass.create", "Create hostel gatepass requests"),
    ("hostel.gatepass.approve", "Approve or reject hostel gatepasses (warden)"),
    (
        "hostel.gatepass.gatekeeper",
        "Mark gatepass checkout / checkin at the gate",
    ),
    ("hostel.gatepass.read", "View hostel gatepasses"),
    ("hostel.reports.read", "View hostel occupancy reports and dashboard"),
]

# Which roles should get every hostel permission. Add more entries to
# bootstrap Warden, Gatekeeper, etc. once those role names exist in the
# database.
ROLES_TO_GRANT = ["Admin"]


def main() -> None:
    app = create_app()
    with app.app_context():
        from core.database import db
        from modules.rbac.models import Permission, Role, RolePermission

        # 1. Upsert hostel permissions globally.
        created_perms = 0
        existing_perm_by_name: dict[str, Permission] = {}
        for name, description in HOSTEL_PERMISSIONS:
            perm = Permission.query.filter_by(name=name).first()
            if perm is None:
                perm = Permission(name=name, description=description)
                db.session.add(perm)
                db.session.flush()
                created_perms += 1
                print(f"  ✓ Created permission: {name}")
            else:
                # Keep the description fresh.
                if description and perm.description != description:
                    perm.description = description
            existing_perm_by_name[name] = perm

        if created_perms:
            print(f"\n  → {created_perms} new permission(s) added.")
        else:
            print("\n  All hostel permissions already exist.")

        # 2. For each target role across every tenant, attach missing perms.
        # Role is TenantBaseModel; querying without tenant context returns all
        # rows because no g.tenant_id is set (the tenant filter is opt-in).
        for role_name in ROLES_TO_GRANT:
            roles = Role.query.filter_by(name=role_name).all()
            if not roles:
                print(f"\n  ⚠ No '{role_name}' role found in any tenant.")
                continue
            print(f"\n  Role '{role_name}' — {len(roles)} tenant(s):")
            for role in roles:
                # role.permissions is the many-to-many that yields Permission
                # rows; pull the junction table directly to know which
                # permission_ids are already linked.
                already = {
                    row.permission_id
                    for row in RolePermission.query.filter_by(role_id=role.id).all()
                }
                added = 0
                for name in (p[0] for p in HOSTEL_PERMISSIONS):
                    perm = existing_perm_by_name[name]
                    if perm.id in already:
                        continue
                    db.session.add(
                        RolePermission(
                            tenant_id=role.tenant_id,
                            role_id=role.id,
                            permission_id=perm.id,
                        )
                    )
                    added += 1
                print(
                    f"    tenant_id={role.tenant_id}: {added} permission(s) granted "
                    f"({len(already)} already linked)"
                )

        db.session.commit()
        print("\n✓ Done.")


if __name__ == "__main__":
    main()
