"""
Sub-Admin module permission catalog.

Single source of truth describing which application modules a School Admin may
grant to a sub-admin, the access "levels" each module offers, and the exact RBAC
permission strings each level/toggle expands to.

Every permission string here is validated against ``scripts/seed_rbac.py``
(the authoritative global permission list). ``subadmin.manage`` is intentionally
NOT present in this catalog and must never be selectable — granting it would let
a sub-admin manage other sub-admins.

Two delete-safety rules drive the design:

1. ``rbac.services.has_permission`` treats ``<resource>.manage`` as granting
   ``<resource>.delete``. For delete-sensitive modules (students, teachers,
   finance) we therefore grant EXPLICIT granular permissions and expose delete
   as a separate opt-in toggle, never ``<resource>.manage``.
2. For coarse modules where delete is acceptable as part of "full access", a
   single ``<resource>.manage`` is used for the manage level (per product
   decision).

Level semantics:
- ``none``  : module not granted (no permissions).
- ``view``  : read-only.
- ``edit``  : view + create/update (delete-sensitive modules).
- ``operate``: view + operational actions (finance only).
- ``manage``: full access incl. delete (coarse modules, or finance "manage"
  toggle).

Optional toggles (only valid when at least ``view``-level is selected):
- ``delete``: adds the resource's delete permission (students/teachers).
- ``refund``: adds ``finance.refund`` (finance).
"""

from typing import Dict, List, Set

# Level keys
LEVEL_NONE = "none"
LEVEL_VIEW = "view"
LEVEL_EDIT = "edit"
LEVEL_OPERATE = "operate"
LEVEL_MANAGE = "manage"

# Toggle keys
TOGGLE_DELETE = "delete"
TOGGLE_REFUND = "refund"


# ---------------------------------------------------------------------------
# Catalog definition
# ---------------------------------------------------------------------------
# Each module declares:
#   label   : human label for the UI
#   levels  : ordered list of level keys it offers (excluding "none")
#   perms   : mapping level -> list of permission strings granted AT that level
#             (cumulative is expressed explicitly per level for clarity)
#   toggles : mapping toggle key -> list of permission strings the toggle adds
#
# NOTE on string choices vs. the task brief:
#   - transport "view" uses ``transport.dashboard.read`` — there is no plain
#     ``transport.read`` in seed_rbac.py; the dashboard read is the closest
#     coarse read permission. transport "manage" uses ``transport.manage``.
#   - announcements has no ``announcement.manage`` permission; "manage" expands
#     to the granular ``announcement.create/update/recall`` set (read.all is the
#     view level).
#   - hostel uses the top-level ``hostel.read`` / ``hostel.manage`` pair; the
#     module's finer sub-permissions are not individually exposed here.

SUBADMIN_MODULES: Dict[str, dict] = {
    # ---- Delete-sensitive: granular perms, explicit delete toggle ----
    "students": {
        "label": "Students",
        "levels": [LEVEL_VIEW, LEVEL_EDIT],
        "perms": {
            LEVEL_VIEW: ["student.read.all"],
            LEVEL_EDIT: ["student.read.all", "student.create", "student.update"],
        },
        "toggles": {
            TOGGLE_DELETE: ["student.delete"],
        },
    },
    "teachers": {
        "label": "Teachers",
        "levels": [LEVEL_VIEW, LEVEL_EDIT],
        "perms": {
            LEVEL_VIEW: ["teacher.read"],
            LEVEL_EDIT: ["teacher.read", "teacher.create", "teacher.update"],
        },
        "toggles": {
            TOGGLE_DELETE: ["teacher.delete"],
        },
    },
    "finance": {
        "label": "Finance & Fees",
        "levels": [LEVEL_VIEW, LEVEL_OPERATE],
        "perms": {
            LEVEL_VIEW: [
                "finance.read",
                "fees.invoice.read",
                "fees.receipt.download",
            ],
            LEVEL_OPERATE: [
                "finance.read",
                "fees.invoice.read",
                "fees.receipt.download",
                "finance.collect",
                "fees.invoice.create",
                "fees.invoice.send_reminder",
                "fees.payment.record",
            ],
        },
        "toggles": {
            TOGGLE_REFUND: ["finance.refund"],
            # "manage" here is a full-access toggle that intentionally grants
            # finance.manage (incl. delete) per product decision.
            LEVEL_MANAGE: ["finance.manage"],
        },
    },
    # ---- Coarse: read + manage (manage intentionally includes delete) ----
    "classes": {
        "label": "Classes",
        "levels": [LEVEL_VIEW, LEVEL_MANAGE],
        "perms": {
            LEVEL_VIEW: ["class.read"],
            LEVEL_MANAGE: ["class.manage"],
        },
        "toggles": {},
    },
    "attendance": {
        "label": "Attendance",
        "levels": [LEVEL_VIEW, LEVEL_MANAGE],
        "perms": {
            LEVEL_VIEW: ["attendance.read.all"],
            LEVEL_MANAGE: ["attendance.manage"],
        },
        "toggles": {},
    },
    "timetable": {
        "label": "Timetable",
        "levels": [LEVEL_VIEW, LEVEL_MANAGE],
        "perms": {
            LEVEL_VIEW: ["timetable.read"],
            LEVEL_MANAGE: ["timetable.manage"],
        },
        "toggles": {},
    },
    "transport": {
        "label": "Transport",
        "levels": [LEVEL_VIEW, LEVEL_MANAGE],
        "perms": {
            # No plain transport.read; dashboard read is the closest coarse read.
            LEVEL_VIEW: ["transport.dashboard.read"],
            LEVEL_MANAGE: ["transport.manage"],
        },
        "toggles": {},
    },
    "academics": {
        "label": "Academics",
        "levels": [LEVEL_VIEW, LEVEL_MANAGE],
        "perms": {
            LEVEL_VIEW: ["academics.read"],
            LEVEL_MANAGE: ["academics.manage"],
        },
        "toggles": {},
    },
    "hostel": {
        "label": "Hostel",
        "levels": [LEVEL_VIEW, LEVEL_MANAGE],
        "perms": {
            LEVEL_VIEW: ["hostel.read"],
            LEVEL_MANAGE: ["hostel.manage"],
        },
        "toggles": {},
    },
    "announcements": {
        "label": "Announcements",
        "levels": [LEVEL_VIEW, LEVEL_MANAGE],
        "perms": {
            LEVEL_VIEW: ["announcement.read.all"],
            # No announcement.manage permission exists; expand to granular set.
            LEVEL_MANAGE: [
                "announcement.read.all",
                "announcement.create",
                "announcement.update",
                "announcement.recall",
            ],
        },
        "toggles": {},
    },
}


# Permission the catalog must never expose or grant.
FORBIDDEN_PERMISSIONS: Set[str] = {"subadmin.manage"}


# Modules whose data is scoped to a branch (school unit) via the Class anchor
# chain in ``core/branch_scope.py``. A branch-restricted sub-admin may ONLY be
# granted modules in this set — granting a non-branch-aware module to a
# restricted sub-admin is rejected (fail-closed) because branch scoping cannot
# be enforced for it. ``finance`` covers both finance and fees.
BRANCH_AWARE_MODULE_KEYS: Set[str] = {
    "classes",
    "students",
    "attendance",
    "finance",
    "timetable",
}


def get_catalog() -> List[dict]:
    """Return the catalog as a UI-friendly list (keys, labels, levels, toggles)."""
    catalog: List[dict] = []
    for key, module in SUBADMIN_MODULES.items():
        catalog.append(
            {
                "key": key,
                "label": module["label"],
                "levels": list(module["levels"]),
                "toggles": list(module["toggles"].keys()),
            }
        )
    return catalog


def expand_selection(selection: List[dict]) -> Set[str]:
    """
    Expand a sub-admin module selection into a flat set of permission strings.

    Args:
        selection: list of dicts ``{"key", "level", "delete"?, "refund"?}``.
            - ``level`` must be one offered by the module (or ``none`` to skip).
            - boolean toggles are only honoured if the module supports them and
              a non-none level is chosen.

    Returns:
        A set of validated permission strings (never includes forbidden perms).

    Raises:
        ValueError: if a key is unknown or a level/toggle is invalid for the
            module — fail loud rather than silently granting nothing.
    """
    permissions: Set[str] = set()

    for item in selection or []:
        key = item.get("key")
        level = item.get("level", LEVEL_NONE)

        if key not in SUBADMIN_MODULES:
            raise ValueError(f"Unknown module key: {key}")

        module = SUBADMIN_MODULES[key]

        if level in (None, LEVEL_NONE):
            continue

        if level not in module["levels"]:
            raise ValueError(f"Invalid level '{level}' for module '{key}'")

        permissions.update(module["perms"][level])

        # Optional toggles
        toggles = module["toggles"]
        if item.get(TOGGLE_DELETE) and TOGGLE_DELETE in toggles:
            permissions.update(toggles[TOGGLE_DELETE])
        if item.get(TOGGLE_REFUND) and TOGGLE_REFUND in toggles:
            permissions.update(toggles[TOGGLE_REFUND])
        # finance full-access "manage" toggle
        if item.get(LEVEL_MANAGE) and LEVEL_MANAGE in toggles:
            permissions.update(toggles[LEVEL_MANAGE])

    # Defence in depth: never let a forbidden permission slip through.
    return permissions - FORBIDDEN_PERMISSIONS


def summarize_permissions(permission_names: List[str]) -> List[dict]:
    """
    Reverse-map a flat permission set back into module/level summaries for
    list/detail display.

    For each module, picks the HIGHEST level fully satisfied by the granted
    permissions, and reports which optional toggles are active. Modules with no
    granted permissions are omitted.

    Args:
        permission_names: flat list of permission strings on the sub-admin role.

    Returns:
        List of ``{"key", "label", "level", "delete", "refund", "manage"}``.
    """
    granted = set(permission_names or [])
    summary: List[dict] = []

    for key, module in SUBADMIN_MODULES.items():
        chosen_level = LEVEL_NONE
        # Iterate levels from lowest to highest; keep the highest fully satisfied.
        for level in module["levels"]:
            required = set(module["perms"][level])
            if required and required.issubset(granted):
                chosen_level = level

        toggles = module["toggles"]
        delete_on = bool(
            TOGGLE_DELETE in toggles and set(toggles[TOGGLE_DELETE]).issubset(granted)
        )
        refund_on = bool(
            TOGGLE_REFUND in toggles and set(toggles[TOGGLE_REFUND]).issubset(granted)
        )
        manage_on = bool(
            LEVEL_MANAGE in toggles and set(toggles[LEVEL_MANAGE]).issubset(granted)
        )

        if chosen_level == LEVEL_NONE and not (delete_on or refund_on or manage_on):
            continue

        summary.append(
            {
                "key": key,
                "label": module["label"],
                "level": chosen_level,
                "delete": delete_on,
                "refund": refund_on,
                "manage": manage_on,
            }
        )

    return summary


def selection_grants_anything(selection: List[dict]) -> bool:
    """Return True if the selection grants at least one permission."""
    try:
        return len(expand_selection(selection)) > 0
    except ValueError:
        return False


def granted_module_keys(selection: List[dict]) -> Set[str]:
    """Return the set of module keys actually granted by the selection.

    A module counts as granted when it has a non-``none`` level or at least one
    active toggle. Unknown keys are ignored here (``expand_selection`` is the
    authoritative validator that rejects them).
    """
    keys: Set[str] = set()
    for item in selection or []:
        key = item.get("key")
        if key not in SUBADMIN_MODULES:
            continue
        level = item.get("level", LEVEL_NONE)
        has_level = level not in (None, LEVEL_NONE)
        has_toggle = bool(
            item.get(TOGGLE_DELETE) or item.get(TOGGLE_REFUND) or item.get(LEVEL_MANAGE)
        )
        if has_level or has_toggle:
            keys.add(key)
    return keys


def non_branch_aware_granted(selection: List[dict]) -> Set[str]:
    """Return granted module keys that are NOT branch-aware (offenders)."""
    return granted_module_keys(selection) - BRANCH_AWARE_MODULE_KEYS
