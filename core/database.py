"""
Database Module

Centralized database instance, Flask-Migrate, and utility functions.
Schema is managed via migrations (flask db upgrade); db.create_all() is not called on init.

Multi-tenant: TenantBaseModel subclasses are automatically filtered by g.tenant_id
when the query runs inside a request that has tenant resolution.
"""

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import Query
from sqlalchemy import event

# Initialize SQLAlchemy instance
# This will be initialized with the app in the application factory
db = SQLAlchemy()
migrate = Migrate()


def _tenant_scope_query(query):
    """
    Apply tenant_id filter to queries for models with __tenant_scoped__.
    Ensures no cross-tenant data leakage when g.tenant_id is set.
    Uses column_descriptions (public API) for SQLAlchemy 1.4/2.0 compatibility.
    """
    from flask import has_request_context, g
    if not has_request_context():
        return query
    tenant_id = getattr(g, "tenant_id", None)
    if tenant_id is None:
        return query
    try:
        for desc in query.column_descriptions:
            entity = desc.get("entity")
            if entity is None:
                continue
            # entity is often the mapped class; support both class and mapper-like
            cls = getattr(entity, "class_", entity) if not isinstance(entity, type) else entity
            if isinstance(cls, type) and getattr(cls, "__tenant_scoped__", False):
                query = query.filter(cls.tenant_id == tenant_id)
            break
    except Exception:
        pass
    return query


def init_db(app):
    """
    Initialize database and migrations with Flask app.
    Tables are created/updated by running: flask db upgrade

    Args:
        app: Flask application instance
    """
    db.init_app(app)
    migrate.init_app(app, db, directory="migrations")

    # Automatically scope tenant-scoped model queries by g.tenant_id
    event.listen(Query, "before_compile", _tenant_scope_query, retval=True)

    with app.app_context():
        from core.models import Tenant, Plan, AuditLog, PlatformSetting
        from modules.auth.models import User, Session
        from modules.rbac.models import Role, Permission, RolePermission, UserRole
        from modules.students.models import Student, StudentDocument
        from modules.academics.academic_year.models import AcademicYear
        from modules.subjects.models import Subject
        from modules.teachers.models import Teacher
        from modules.classes.models import Class, ClassTeacher, ClassSubject
        from modules.academics.backbone.models import (
            AcademicSettings,
            AcademicTerm,
            AttendanceRecord,
            AttendanceSession,
            BellSchedule,
            BellSchedulePeriod,
            ClassSubjectTeacher,
            ClassTeacherAssignment,
            StudentClassEnrollment,
            TimetableEntry,
            TimetableVersion,
        )
        from modules.attendance.models import Attendance
        from modules.finance.models import (
            FeeStructure,
            FeeStructureClass,
            FeeComponent,
            StudentFee,
            StudentFeeItem,
            Payment,
        )
        from modules.fees.models import (
            FeeInvoice,
            FeeInvoiceItem,
            FeePayment,
            FeeReceipt,
        )
        from modules.notifications.models import (
            Notification,
            NotificationRecipient,
            NotificationTemplate,
        )
        from modules.timetable.models import TimetableSlot, TimetableConfig
        from modules.schedule.models import ScheduleOverride
        from modules.holidays.models import Holiday
        from modules.devices.models import DeviceToken
        from modules.transport.models import (
            TransportBus,
            TransportBusAssignment,
            TransportDriver,
            TransportEnrollment,
            TransportFeePlan,
            TransportRoute,
            TransportStaff,
            TransportStop,
        )


def reset_db(app):
    """
    Drop all tables and recreate them. USE WITH CAUTION!
    Only for development/testing purposes.
    
    Args:
        app: Flask application instance
    """
    with app.app_context():
        db.drop_all()
        db.create_all()
