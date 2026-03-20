"""
Platform Admin Services

Business logic for platform (super admin) operations: dashboard, tenant CRUD,
school admin creation, plan changes, audit. All operations are platform-scoped
(no g.tenant_id); tenant_id is passed explicitly where needed.
"""

import secrets
import string
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Any

from backend.core.database import db
from backend.core.models import (
    Tenant,
    Plan,
    AuditLog,
    PlatformSetting,
    TENANT_STATUS_ACTIVE,
    TENANT_STATUS_SUSPENDED,
    TENANT_STATUS_DELETED,
)
from backend.modules.auth.models import User
from backend.modules.rbac.models import Role, Permission, RolePermission, UserRole
from backend.modules.rbac.role_seeder import DEFAULT_ROLES, seed_roles_for_tenant  # noqa: F401 (re-exported)
from backend.modules.students.models import Student
from backend.modules.teachers.models import Teacher
from backend.modules.platform.audit import log_platform_action


def _generate_strong_password(length: int = 16) -> str:
    """Generate a strong random password (letters + digits + symbols)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def get_dashboard_stats() -> Dict[str, Any]:
    """Aggregate stats for platform dashboard."""
    from sqlalchemy import func

    # Exclude deleted tenants from all counts
    tenants = Tenant.query.filter(
        Tenant.status.in_([TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED])
    ).all()
    total_tenants = len(tenants)
    active_tenants = sum(1 for t in tenants if t.status == TENANT_STATUS_ACTIVE)
    suspended_tenants = sum(1 for t in tenants if t.status == TENANT_STATUS_SUSPENDED)

    total_students = db.session.query(Student).count()
    total_teachers = db.session.query(Teacher).count()

    revenue_row = (
        db.session.query(func.coalesce(func.sum(Plan.price_monthly), 0))
        .select_from(Tenant)
        .join(Plan, Tenant.plan_id == Plan.id)
        .filter(Tenant.status == TENANT_STATUS_ACTIVE)
        .scalar()
    )
    revenue_monthly = revenue_row if revenue_row is not None else Decimal("0")

    # Tenant growth by month (created_at); exclude deleted
    growth_q = (
        db.session.query(
            func.date_trunc("month", Tenant.created_at).label("month"),
            func.count(Tenant.id).label("count"),
        )
        .filter(
            Tenant.status.in_([TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED])
        )
        .group_by(func.date_trunc("month", Tenant.created_at))
        .order_by(func.date_trunc("month", Tenant.created_at))
        .all()
    )
    tenant_growth_by_month = [
        {"month": m.isoformat() if m else None, "count": c}
        for m, c in growth_q
    ]

    return {
        "total_tenants": total_tenants,
        "active_tenants": active_tenants,
        "suspended_tenants": suspended_tenants,
        "total_students": total_students,
        "total_teachers": total_teachers,
        "revenue_monthly": float(revenue_monthly),
        "tenant_growth_by_month": tenant_growth_by_month,
    }


def create_tenant(
    name: str,
    subdomain: str,
    contact_email: Optional[str],
    phone: Optional[str],
    address: Optional[str],
    plan_id: str,
    admin_email: str,
    admin_name: str,
    platform_admin_id: str,
    login_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create tenant, seed roles, create school admin user, assign Admin role,
    send credentials email, and log audit.
    """
    subdomain = subdomain.strip().lower()
    if Tenant.query.filter_by(subdomain=subdomain).first():
        return {"success": False, "error": "Subdomain already exists"}

    plan = Plan.query.get(plan_id)
    if not plan:
        return {"success": False, "error": "Plan not found"}

    # School admin email must be unique within the new tenant; we create tenant first so no conflict yet
    tenant = Tenant(
        name=name,
        subdomain=subdomain,
        contact_email=contact_email,
        phone=phone,
        address=address,
        plan_id=plan_id,
        status=TENANT_STATUS_ACTIVE,
    )
    db.session.add(tenant)
    db.session.flush()
    tenant_id = tenant.id

    seed_roles_for_tenant(tenant_id)
    admin_role = Role.query.filter_by(name="Admin", tenant_id=tenant_id).first()
    if not admin_role:
        db.session.rollback()
        return {"success": False, "error": "Failed to create Admin role for tenant"}

    password = _generate_strong_password()
    user = User(
        tenant_id=tenant_id,
        email=admin_email,
        name=admin_name or admin_email,
    )
    user.set_password(password)
    user.force_password_reset = True
    user.email_verified = True
    db.session.add(user)
    db.session.flush()

    ur = UserRole(tenant_id=tenant_id, user_id=user.id, role_id=admin_role.id)
    db.session.add(ur)
    db.session.commit()

    try:
        from backend.modules.notifications.services import notification_dispatcher
        from backend.modules.notifications.enums import NotificationChannel

        notification_dispatcher.dispatch(
            user_id=user.id,
            tenant_id=tenant_id,
            notification_type="ADMIN_CREDENTIALS",
            channels=[NotificationChannel.EMAIL.value],
            title="Your School Admin Account",
            body=None,
            extra_data={
                "admin_name": admin_name or admin_email,
                "tenant_name": name,
                "admin_email": admin_email,
                "password": password,
                "login_url": login_url or "",
            },
        )
    except Exception:
        # Log but do not fail tenant creation
        pass

    log_platform_action(
        platform_admin_id=platform_admin_id,
        action="tenant.created",
        tenant_id=tenant_id,
        metadata={"subdomain": subdomain, "admin_email": admin_email},
    )

    return {
        "success": True,
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "subdomain": tenant.subdomain,
            "status": tenant.status,
            "plan_id": tenant.plan_id,
        },
        "admin_user_id": user.id,
    }


def suspend_tenant(tenant_id: str, platform_admin_id: str) -> Dict[str, Any]:
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}
    tenant.status = TENANT_STATUS_SUSPENDED
    tenant.updated_at = datetime.utcnow()
    db.session.commit()
    log_platform_action(
        platform_admin_id=platform_admin_id,
        action="tenant.suspended",
        tenant_id=tenant_id,
        metadata={},
    )
    return {"success": True, "tenant": {"id": tenant.id, "status": tenant.status}}


def activate_tenant(tenant_id: str, platform_admin_id: str) -> Dict[str, Any]:
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}
    tenant.status = TENANT_STATUS_ACTIVE
    tenant.updated_at = datetime.utcnow()
    db.session.commit()
    log_platform_action(
        platform_admin_id=platform_admin_id,
        action="tenant.activated",
        tenant_id=tenant_id,
        metadata={},
    )
    return {"success": True, "tenant": {"id": tenant.id, "status": tenant.status}}


def change_tenant_plan(tenant_id: str, plan_id: str, platform_admin_id: str) -> Dict[str, Any]:
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}
    plan = Plan.query.get(plan_id)
    if not plan:
        return {"success": False, "error": "Plan not found"}
    old_plan_id = tenant.plan_id
    tenant.plan_id = plan_id
    tenant.updated_at = datetime.utcnow()
    db.session.commit()
    log_platform_action(
        platform_admin_id=platform_admin_id,
        action="plan.changed",
        tenant_id=tenant_id,
        metadata={"old_plan_id": old_plan_id, "new_plan_id": plan_id},
    )
    return {"success": True, "tenant": {"id": tenant.id, "plan_id": tenant.plan_id}}


def get_school_admin_user_for_tenant(tenant_id: str) -> Optional[User]:
    """Return the first user in the tenant with Admin role (school admin)."""
    admin_role = Role.query.filter_by(name="Admin", tenant_id=tenant_id).first()
    if not admin_role:
        return None
    ur = UserRole.query.filter_by(tenant_id=tenant_id, role_id=admin_role.id).first()
    if not ur:
        return None
    return User.query.get(ur.user_id)


def reset_tenant_admin(tenant_id: str, platform_admin_id: str) -> Dict[str, Any]:
    """
    Generate new password for school admin, set force_password_reset=True,
    send email, log audit.
    """
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}
    user = get_school_admin_user_for_tenant(tenant_id)
    if not user:
        return {"success": False, "error": "No school admin user found for this tenant"}

    password = _generate_strong_password()
    user.set_password(password)
    user.force_password_reset = True
    user.save()

    try:
        from backend.modules.notifications.services import notification_dispatcher
        from backend.modules.notifications.enums import NotificationChannel

        notification_dispatcher.dispatch(
            user_id=user.id,
            tenant_id=tenant_id,
            notification_type="ADMIN_PASSWORD_RESET",
            channels=[NotificationChannel.EMAIL.value],
            title="Your School Admin Password Has Been Reset",
            body=None,
            extra_data={
                "admin_name": user.name or user.email,
                "tenant_name": tenant.name,
                "admin_email": user.email,
                "password": password,
                "login_url": "",
            },
        )
    except Exception:
        pass

    log_platform_action(
        platform_admin_id=platform_admin_id,
        action="school_admin.reset",
        tenant_id=tenant_id,
        metadata={"admin_email": user.email},
    )
    return {"success": True, "message": "Password reset and email sent"}


def list_tenants(
    page: int = 1,
    per_page: int = 20,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Paginated list of tenants with plan name, student count, teacher count, status."""
    query = Tenant.query
    if status:
        query = query.filter(Tenant.status == status)
    query = query.order_by(Tenant.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    items = []
    for t in pagination.items:
        plan_name = t.plan.name if t.plan else None
        student_count = Student.query.filter_by(tenant_id=t.id).count()
        teacher_count = Teacher.query.filter_by(tenant_id=t.id).count()
        items.append({
            "id": t.id,
            "name": t.name,
            "subdomain": t.subdomain,
            "contact_email": t.contact_email,
            "status": t.status,
            "plan_id": t.plan_id,
            "plan_name": plan_name,
            "student_count": student_count,
            "teacher_count": teacher_count,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return {
        "success": True,
        "data": items,
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        },
    }


def get_tenant_by_id(tenant_id: str) -> Dict[str, Any]:
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}
    student_count = Student.query.filter_by(tenant_id=tenant_id).count()
    teacher_count = Teacher.query.filter_by(tenant_id=tenant_id).count()
    tenant_data = {
        "id": tenant.id,
        "name": tenant.name,
        "subdomain": tenant.subdomain,
        "contact_email": tenant.contact_email,
        "phone": tenant.phone,
        "address": tenant.address,
        "logo_url": tenant.logo_url,
        "tagline": tenant.tagline,
        "board_affiliation": tenant.board_affiliation,
        "status": tenant.status,
        "plan_id": tenant.plan_id,
        "plan_name": tenant.plan.name if tenant.plan else None,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "student_count": student_count,
        "teacher_count": teacher_count,
    }
    return {"success": True, "tenant": tenant_data}


def update_tenant(
    tenant_id: str,
    platform_admin_id: str,
    name: Optional[str] = None,
    contact_email: Optional[str] = None,
    phone: Optional[str] = None,
    address: Optional[str] = None,
    logo_url: Optional[str] = None,
    tagline: Optional[str] = None,
    board_affiliation: Optional[str] = None,
) -> Dict[str, Any]:
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}
    if name is not None:
        tenant.name = name
    if contact_email is not None:
        tenant.contact_email = contact_email
    if phone is not None:
        tenant.phone = phone
    if address is not None:
        tenant.address = address
    if logo_url is not None:
        tenant.logo_url = logo_url or None
    if tagline is not None:
        tenant.tagline = tagline or None
    if board_affiliation is not None:
        tenant.board_affiliation = board_affiliation or None
    tenant.updated_at = datetime.utcnow()
    db.session.commit()
    log_platform_action(
        platform_admin_id=platform_admin_id,
        action="tenant.updated",
        tenant_id=tenant_id,
        metadata={"updated_fields": ["name", "contact_email", "phone", "address", "logo_url", "tagline", "board_affiliation"]},
    )
    return {"success": True, "tenant": {"id": tenant.id}}


def delete_tenant(tenant_id: str, platform_admin_id: str) -> Dict[str, Any]:
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}
    tenant.status = TENANT_STATUS_DELETED
    tenant.updated_at = datetime.utcnow()
    db.session.commit()
    log_platform_action(
        platform_admin_id=platform_admin_id,
        action="tenant.deleted",
        tenant_id=tenant_id,
        metadata={"subdomain": tenant.subdomain},
    )
    return {"success": True}

def list_plans() -> List[Dict[str, Any]]:
    """List all plans for dropdowns (e.g. tenant creation)."""
    plans = Plan.query.order_by(Plan.price_monthly).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "price_monthly": float(p.price_monthly),
            "max_students": p.max_students,
            "max_teachers": p.max_teachers,
            "features_json": p.features_json,
        }
        for p in plans
    ]


def create_plan(
    name: str,
    price_monthly: float,
    max_students: int,
    max_teachers: int,
    features_json: Optional[dict] = None,
    platform_admin_id: Optional[str] = None,
) -> Dict[str, Any]:
    if Plan.query.filter_by(name=name).first():
        return {"success": False, "error": "Plan name already exists"}
    plan = Plan(
        name=name,
        price_monthly=Decimal(str(price_monthly)),
        max_students=max_students,
        max_teachers=max_teachers,
        features_json=features_json,
    )
    db.session.add(plan)
    db.session.commit()
    if platform_admin_id:
        log_platform_action(
            platform_admin_id=platform_admin_id,
            action="plan.created",
            tenant_id=None,
            metadata={"plan_id": plan.id, "name": plan.name},
        )
    return {"success": True, "plan": {"id": plan.id, "name": plan.name}}


def update_plan(
    plan_id: str,
    platform_admin_id: Optional[str],
    name: Optional[str] = None,
    price_monthly: Optional[float] = None,
    max_students: Optional[int] = None,
    max_teachers: Optional[int] = None,
    features_json: Optional[dict] = None,
) -> Dict[str, Any]:
    plan = Plan.query.get(plan_id)
    if not plan:
        return {"success": False, "error": "Plan not found"}
    if name is not None:
        existing = Plan.query.filter_by(name=name).first()
        if existing and existing.id != plan_id:
            return {"success": False, "error": "Plan name already exists"}
        plan.name = name
    if price_monthly is not None:
        plan.price_monthly = Decimal(str(price_monthly))
    if max_students is not None:
        plan.max_students = max_students
    if max_teachers is not None:
        plan.max_teachers = max_teachers
    if features_json is not None:
        plan.features_json = features_json
    plan.updated_at = datetime.utcnow()
    db.session.commit()
    if platform_admin_id:
        log_platform_action(
            platform_admin_id=platform_admin_id,
            action="plan.updated",
            tenant_id=None,
            metadata={"plan_id": plan_id},
        )
    return {"success": True, "plan": {"id": plan.id}}


def delete_plan(plan_id: str, platform_admin_id: Optional[str] = None) -> Dict[str, Any]:
    plan = Plan.query.get(plan_id)
    if not plan:
        return {"success": False, "error": "Plan not found"}
    if Tenant.query.filter_by(plan_id=plan_id).first():
        return {"success": False, "error": "Cannot delete plan: tenants are using it"}
    db.session.delete(plan)
    db.session.commit()
    if platform_admin_id:
        log_platform_action(
            platform_admin_id=platform_admin_id,
            action="plan.deleted",
            tenant_id=None,
            metadata={"plan_id": plan_id, "name": plan.name},
        )
    return {"success": True}


def list_audit_logs(
    page: int = 1,
    per_page: int = 20,
    action: Optional[str] = None,
    tenant_id: Optional[str] = None,
    platform_admin_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    query = AuditLog.query
    if action:
        query = query.filter(AuditLog.action == action)
    if tenant_id:
        query = query.filter(AuditLog.tenant_id == tenant_id)
    if platform_admin_id:
        query = query.filter(AuditLog.platform_admin_id == platform_admin_id)
    if date_from:
        try:
            from datetime import datetime as dt
            start = dt.fromisoformat(date_from.replace("Z", "+00:00"))
            query = query.filter(AuditLog.created_at >= start)
        except ValueError:
            pass
    if date_to:
        try:
            from datetime import datetime as dt
            end = dt.fromisoformat(date_to.replace("Z", "+00:00"))
            query = query.filter(AuditLog.created_at <= end)
        except ValueError:
            pass
    query = query.order_by(AuditLog.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    items = []
    for log in pagination.items:
        items.append({
            "id": log.id,
            "action": log.action,
            "tenant_id": log.tenant_id,
            "platform_admin_id": log.platform_admin_id,
            "extra_data": log.extra_data,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })
    return {
        "success": True,
        "data": items,
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        },
    }


def list_tenant_admins(tenant_id: str) -> Dict[str, Any]:
    """List users with Admin role for the given tenant."""
    admin_role = Role.query.filter_by(name="Admin", tenant_id=tenant_id).first()
    if not admin_role:
        return {"success": True, "admins": []}
    role_user_ids = [ur.user_id for ur in UserRole.query.filter_by(tenant_id=tenant_id, role_id=admin_role.id).all()]
    admins = []
    for uid in role_user_ids:
        user = User.query.get(uid)
        if user:
            admins.append({
                "id": user.id,
                "email": user.email,
                "name": user.name,
            })
    return {"success": True, "admins": admins}


def add_tenant_admin(
    tenant_id: str,
    email: str,
    name: Optional[str],
    platform_admin_id: str,
    login_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an additional school admin user for the tenant and assign Admin role."""
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}
    existing = User.query.filter_by(tenant_id=tenant_id, email=email).first()
    if existing:
        return {"success": False, "error": "A user with this email already exists for this tenant"}
    admin_role = Role.query.filter_by(name="Admin", tenant_id=tenant_id).first()
    if not admin_role:
        return {"success": False, "error": "Admin role not found for tenant"}
    password = _generate_strong_password()
    user = User(
        tenant_id=tenant_id,
        email=email,
        name=name or email,
    )
    user.set_password(password)
    user.force_password_reset = True
    user.email_verified = True
    db.session.add(user)
    db.session.flush()
    ur = UserRole(tenant_id=tenant_id, user_id=user.id, role_id=admin_role.id)
    db.session.add(ur)
    db.session.commit()
    try:
        from backend.modules.notifications.services import notification_dispatcher
        from backend.modules.notifications.enums import NotificationChannel

        notification_dispatcher.dispatch(
            user_id=user.id,
            tenant_id=tenant_id,
            notification_type="ADMIN_CREDENTIALS",
            channels=[NotificationChannel.EMAIL.value],
            title="Your School Admin Account",
            body=None,
            extra_data={
                "admin_name": name or email,
                "tenant_name": tenant.name,
                "admin_email": email,
                "password": password,
                "login_url": login_url or "",
            },
        )
    except Exception:
        pass
    log_platform_action(
        platform_admin_id=platform_admin_id,
        action="school_admin.created",
        tenant_id=tenant_id,
        metadata={"admin_email": email},
    )
    return {"success": True, "admin_user_id": user.id}


def remove_tenant_admin(
    tenant_id: str,
    admin_user_id: str,
    platform_admin_id: str,
) -> Dict[str, Any]:
    """Remove Admin role from a user for the given tenant. Keeps user record; revokes admin access."""
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}
    user = User.query.filter_by(id=admin_user_id, tenant_id=tenant_id).first()
    if not user:
        return {"success": False, "error": "Admin user not found for this tenant"}
    admin_role = Role.query.filter_by(name="Admin", tenant_id=tenant_id).first()
    if not admin_role:
        return {"success": False, "error": "Admin role not found for tenant"}
    admin_user_count = UserRole.query.filter_by(
        tenant_id=tenant_id,
        role_id=admin_role.id,
    ).count()
    if admin_user_count <= 1:
        return {"success": False, "error": "Cannot remove the last admin. A tenant must have at least one admin."}
    ur = UserRole.query.filter_by(
        tenant_id=tenant_id,
        user_id=admin_user_id,
        role_id=admin_role.id,
    ).first()
    if not ur:
        return {"success": False, "error": "User is not an admin for this tenant"}
    db.session.delete(ur)
    remaining_roles = UserRole.query.filter_by(tenant_id=tenant_id, user_id=admin_user_id).count()
    has_student = Student.query.filter_by(tenant_id=tenant_id, user_id=admin_user_id).first() is not None
    has_teacher = Teacher.query.filter_by(tenant_id=tenant_id, user_id=admin_user_id).first() is not None
    if remaining_roles == 0 and not has_student and not has_teacher:
        db.session.delete(user)
    db.session.commit()
    log_platform_action(
        platform_admin_id=platform_admin_id,
        action="school_admin.removed",
        tenant_id=tenant_id,
        metadata={"admin_user_id": admin_user_id, "admin_email": user.email},
    )
    return {"success": True}


def update_tenant_admin(
    tenant_id: str,
    admin_user_id: str,
    platform_admin_id: str,
    name: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a school admin user's name and/or email for the given tenant."""
    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}
    user = User.query.filter_by(id=admin_user_id, tenant_id=tenant_id).first()
    if not user:
        return {"success": False, "error": "Admin user not found for this tenant"}
    admin_role = Role.query.filter_by(name="Admin", tenant_id=tenant_id).first()
    if not admin_role:
        return {"success": False, "error": "Admin role not found for tenant"}
    ur = UserRole.query.filter_by(
        tenant_id=tenant_id,
        user_id=admin_user_id,
        role_id=admin_role.id,
    ).first()
    if not ur:
        return {"success": False, "error": "User is not an admin for this tenant"}
    if name is not None:
        user.name = name
    if email is not None:
        if email.strip() == "":
            return {"success": False, "error": "Email cannot be empty"}
        existing = User.query.filter_by(tenant_id=tenant_id, email=email).first()
        if existing and existing.id != admin_user_id:
            return {"success": False, "error": "A user with this email already exists for this tenant"}
        user.email = email.strip()
    db.session.commit()
    log_platform_action(
        platform_admin_id=platform_admin_id,
        action="school_admin.updated",
        tenant_id=tenant_id,
        metadata={"admin_user_id": admin_user_id, "admin_email": user.email},
    )
    return {"success": True}


def get_platform_settings() -> Dict[str, Any]:
    """Return all platform settings as key -> value (strings)."""
    from backend.core.models import PLATFORM_SETTING_KEYS
    rows = PlatformSetting.query.all()
    result = {r.key: r.value for r in rows}
    for key in PLATFORM_SETTING_KEYS:
        if key not in result:
            result[key] = None
    return result


def get_platform_setting(key: str) -> Optional[str]:
    """Return a single platform setting value, or None if unset."""
    row = PlatformSetting.query.get(key)
    if row is None or row.value is None:
        return None
    return str(row.value)


# --- Notification templates and tenant notification settings ---

def get_tenant_notification_settings(tenant_id: str) -> Dict[str, Any]:
    """Get tenant's notification template overrides (tenant_id = tenant)."""
    from backend.modules.notifications.models import NotificationTemplate

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}

    templates = NotificationTemplate.query.filter_by(tenant_id=tenant_id).all()
    return {
        "success": True,
        "tenant_id": tenant_id,
        "templates": [t.to_dict() for t in templates],
    }


def patch_tenant_notification_settings(
    tenant_id: str,
    templates: List[Dict[str, Any]],
    platform_admin_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update tenant override templates."""
    from backend.modules.notifications.models import NotificationTemplate
    from backend.modules.notifications.template_service import NOTIFICATION_CATEGORIES

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}

    if not isinstance(templates, list):
        return {"success": False, "error": "templates must be a list"}

    for item in templates:
        t_id = item.get("id")
        t_type = item.get("type")
        channel = item.get("channel")
        category = item.get("category")
        subject_template = item.get("subject_template")
        body_template = item.get("body_template")

        if not t_type or not channel or not category:
            return {"success": False, "error": "type, channel, category required"}
        if category not in NOTIFICATION_CATEGORIES:
            return {"success": False, "error": f"Invalid category: {category}"}
        if not subject_template or not body_template:
            return {"success": False, "error": "subject_template and body_template required"}

        if t_id:
            tpl = NotificationTemplate.query.filter_by(id=t_id, tenant_id=tenant_id).first()
            if not tpl:
                return {"success": False, "error": "Template not found"}
            tpl.type = t_type
            tpl.channel = channel
            tpl.category = category
            tpl.subject_template = subject_template
            tpl.body_template = body_template
        else:
            existing = NotificationTemplate.query.filter_by(
                tenant_id=tenant_id, type=t_type, channel=channel
            ).first()
            if existing:
                existing.subject_template = subject_template
                existing.body_template = body_template
                existing.category = category
            else:
                tpl = NotificationTemplate(
                    tenant_id=tenant_id,
                    type=t_type,
                    channel=channel,
                    category=category,
                    is_system=False,
                    subject_template=subject_template,
                    body_template=body_template,
                )
                db.session.add(tpl)

    db.session.commit()
    if platform_admin_id:
        log_platform_action(
            platform_admin_id=platform_admin_id,
            action="tenant.notification_settings.updated",
            tenant_id=tenant_id,
            metadata={},
        )
    return {"success": True, "tenant_id": tenant_id}


def list_notification_templates(
    tenant_id: Optional[str] = None,
    category: Optional[str] = None,
    template_type: Optional[str] = None,
    channel: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> Dict[str, Any]:
    """List notification templates with optional filters."""
    from backend.modules.notifications.models import NotificationTemplate

    query = NotificationTemplate.query
    if tenant_id is not None:
        if tenant_id == "" or tenant_id.lower() == "null":
            query = query.filter(NotificationTemplate.tenant_id.is_(None))
        else:
            query = query.filter(NotificationTemplate.tenant_id == tenant_id)
    if category:
        query = query.filter(NotificationTemplate.category == category)
    if template_type:
        query = query.filter(NotificationTemplate.type == template_type)
    if channel:
        query = query.filter(NotificationTemplate.channel == channel)

    query = query.order_by(NotificationTemplate.category, NotificationTemplate.type, NotificationTemplate.channel)
    per_page = min(max(per_page, 1), 100)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    items = [t.to_dict() for t in pagination.items]
    return {
        "success": True,
        "items": items,
        "pagination": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        },
    }


def create_notification_template(
    template_type: str,
    channel: str,
    category: str,
    subject_template: str,
    body_template: str,
    tenant_id: Optional[str] = None,
    is_system: bool = False,
    platform_admin_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a notification template (global if tenant_id None)."""
    from backend.modules.notifications.models import NotificationTemplate
    from backend.modules.notifications.template_service import NOTIFICATION_CATEGORIES
    import uuid

    if category not in NOTIFICATION_CATEGORIES:
        return {"success": False, "error": f"Invalid category: {category}"}

    from backend.modules.notifications.template_service import validate_notification_template
    valid, err = validate_notification_template(subject_template, body_template)
    if not valid:
        return {"success": False, "error": f"Invalid template syntax: {err}"}

    # Default template content for new types when not provided
    DEFAULT_SUBJECT_TEMPLATE = "{{ school_name }} Notification"
    DEFAULT_BODY_TEMPLATE = "<p>Hello {{ user_name }},</p><p>{{ message }}</p>"
    if not subject_template or not subject_template.strip():
        subject_template = DEFAULT_SUBJECT_TEMPLATE
    if not body_template or not body_template.strip():
        body_template = DEFAULT_BODY_TEMPLATE

    q = NotificationTemplate.query.filter(
        NotificationTemplate.type == template_type,
        NotificationTemplate.channel == channel,
    )
    if tenant_id:
        q = q.filter(NotificationTemplate.tenant_id == tenant_id)
    else:
        q = q.filter(NotificationTemplate.tenant_id.is_(None))
    existing = q.first()
    if existing:
        return {"success": False, "error": "Template already exists for this tenant/type/channel"}

    tpl = NotificationTemplate(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        type=template_type,
        channel=channel,
        category=category,
        is_system=is_system,
        subject_template=subject_template,
        body_template=body_template,
    )
    db.session.add(tpl)
    db.session.commit()
    if platform_admin_id:
        log_platform_action(
            platform_admin_id=platform_admin_id,
            action="notification_template.created",
            tenant_id=tenant_id,
            metadata={"template_id": tpl.id, "type": template_type, "channel": channel},
        )
    return {"success": True, "template": tpl.to_dict()}


def update_notification_template(
    template_id: str,
    platform_admin_id: Optional[str],
    type: Optional[str] = None,
    channel: Optional[str] = None,
    category: Optional[str] = None,
    subject_template: Optional[str] = None,
    body_template: Optional[str] = None,
    is_system: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update a notification template."""
    from backend.modules.notifications.models import NotificationTemplate
    from backend.modules.notifications.template_service import NOTIFICATION_CATEGORIES

    tpl = NotificationTemplate.query.get(template_id)
    if not tpl:
        return {"success": False, "error": "Template not found"}
    if category is not None and category not in NOTIFICATION_CATEGORIES:
        return {"success": False, "error": f"Invalid category: {category}"}

    subj = subject_template if subject_template is not None else tpl.subject_template
    body = body_template if body_template is not None else tpl.body_template
    from backend.modules.notifications.template_service import validate_notification_template
    valid, err = validate_notification_template(subj, body)
    if not valid:
        return {"success": False, "error": f"Invalid template syntax: {err}"}

    if type is not None:
        tpl.type = type
    if channel is not None:
        tpl.channel = channel
    if category is not None:
        tpl.category = category
    if subject_template is not None:
        tpl.subject_template = subject_template
    if body_template is not None:
        tpl.body_template = body_template
    if is_system is not None:
        tpl.is_system = is_system

    db.session.commit()
    if platform_admin_id:
        log_platform_action(
            platform_admin_id=platform_admin_id,
            action="notification_template.updated",
            tenant_id=tpl.tenant_id,
            metadata={"template_id": template_id},
        )
    return {"success": True, "template": tpl.to_dict()}


def delete_notification_template(template_id: str, platform_admin_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete a notification template."""
    from backend.modules.notifications.models import NotificationTemplate

    tpl = NotificationTemplate.query.get(template_id)
    if not tpl:
        return {"success": False, "error": "Template not found"}
    tenant_id = tpl.tenant_id
    db.session.delete(tpl)
    db.session.commit()
    if platform_admin_id:
        log_platform_action(
            platform_admin_id=platform_admin_id,
            action="notification_template.deleted",
            tenant_id=tenant_id,
            metadata={"template_id": template_id},
        )
    return {"success": True}


def preview_notification_template(
    template_id: Optional[str] = None,
    subject_template: Optional[str] = None,
    body_template: Optional[str] = None,
) -> Dict[str, Any]:
    """Render template with dummy context. Either template_id or (subject_template, body_template) required."""
    from backend.modules.notifications.models import NotificationTemplate
    from backend.modules.notifications.template_service import (
        render_notification_template,
        PREVIEW_CONTEXT,
    )

    if template_id:
        tpl = NotificationTemplate.query.get(template_id)
        if not tpl:
            return {"success": False, "error": "Template not found"}
        subject_template = tpl.subject_template
        body_template = tpl.body_template
    elif subject_template is not None and body_template is not None:
        pass
    else:
        return {"success": False, "error": "Either template_id or subject_template and body_template required"}

    try:
        subj, body = render_notification_template(
            subject_template or "",
            body_template or "",
            PREVIEW_CONTEXT,
        )
        return {"success": True, "subject": subj, "body": body}
    except Exception as e:
        return {"success": False, "error": str(e)}


def test_send_notification_template(template_id: str, to_email: str) -> Dict[str, Any]:
    """Render template and send to given email. Used for test-send to super admin."""
    from backend.modules.notifications.models import NotificationTemplate
    from backend.modules.notifications.template_service import (
        render_notification_template,
        PREVIEW_CONTEXT,
    )
    from backend.tasks.notifications import send_email_task

    tpl = NotificationTemplate.query.get(template_id)
    if not tpl:
        return {"success": False, "error": "Template not found"}

    try:
        subj, body = render_notification_template(
            tpl.subject_template,
            tpl.body_template,
            PREVIEW_CONTEXT,
        )
        send_email_task.delay(to_email, subj, body or "", is_html=True)
        return {"success": True, "message": "Test email sent"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_platform_settings(updates: Dict[str, Any], platform_admin_id: Optional[str] = None) -> Dict[str, Any]:
    """Update platform settings. Values are stored as strings."""
    from backend.core.models import PLATFORM_SETTING_KEYS
    for key, value in updates.items():
        if key not in PLATFORM_SETTING_KEYS:
            continue
        if value is None or value == "":
            stored = PlatformSetting.query.get(key)
            if stored:
                db.session.delete(stored)
        else:
            stored = PlatformSetting.query.get(key)
            str_val = str(value).lower() if isinstance(value, bool) else str(value)
            if stored:
                stored.value = str_val
                stored.updated_at = datetime.utcnow()
            else:
                db.session.add(PlatformSetting(key=key, value=str_val))
    db.session.commit()
    if platform_admin_id:
        log_platform_action(
            platform_admin_id=platform_admin_id,
            action="settings.updated",
            tenant_id=None,
            metadata={"keys": list(updates.keys())},
        )
    return {"success": True}
