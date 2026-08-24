"""
Database Module

Centralized database instance, Flask-Migrate, and utility functions.
Schema is managed via migrations (flask db upgrade); db.create_all() is not called on init.

Multi-tenant: TenantBaseModel subclasses are automatically filtered by g.tenant_id
when the query runs inside a request that has tenant resolution.
"""

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
# Aliased: `init_db` locally imports modules.auth.models.Session (the user-session
# model), which would otherwise shadow this ORM Session in the function scope.
from sqlalchemy.orm import Session as OrmSession, with_loader_criteria

# Initialize SQLAlchemy instance
# This will be initialized with the app in the application factory
db = SQLAlchemy()
migrate = Migrate()


def _tenant_scope_execute(execute_state):
    """
    Inject a ``tenant_id`` WHERE criterion into every ORM SELECT that touches a
    ``TenantBaseModel`` subclass, scoped to the request's ``g.tenant_id``.

    This uses ``with_loader_criteria`` rather than the legacy ``before_compile``
    hook because ``before_compile`` silently *drops* an added WHERE clause when
    the query already has LIMIT/OFFSET (the criterion would have to move inside a
    subquery). That made ``count()`` scope correctly while the paginated
    ``limit().offset().all()`` leaked every tenant's rows — a cross-tenant data
    leak on every list endpoint. ``with_loader_criteria`` is applied at execution
    time and is safe under LIMIT/OFFSET, JOINs, aliases and subqueries.

    Only primary entity SELECTs are scoped; relationship lazy-loads and column
    refreshes are reached through already-scoped parents and are skipped so we
    don't interfere with identity-map loads.
    """
    from flask import has_request_context, g
    from core.models import TenantBaseModel

    if not has_request_context():
        return
    if not execute_state.is_select:
        return
    if execute_state.is_column_load or execute_state.is_relationship_load:
        return
    tenant_id = getattr(g, "tenant_id", None)
    if tenant_id is None:
        return

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantBaseModel,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


def init_db(app):
    """
    Initialize database and migrations with Flask app.
    Tables are created/updated by running: flask db upgrade

    Args:
        app: Flask application instance
    """
    db.init_app(app)
    migrate.init_app(app, db, directory="migrations")

    # Automatically scope tenant-scoped model SELECTs by g.tenant_id.
    # do_orm_execute + with_loader_criteria is LIMIT/OFFSET-safe (see the
    # handler docstring); listen on the base Session so all sessions are covered.
    event.listen(OrmSession, "do_orm_execute", _tenant_scope_execute)

    with app.app_context():
        from core.models import Tenant, Plan, AuditLog, PlatformSetting
        from modules.auth.models import User, Session
        from modules.rbac.models import Role, Permission, RolePermission
        from modules.sub_admins.models import UserSchoolUnit  # noqa: F401
        from modules.students.models import Student, StudentPromotionBatch
        from modules.documents.models import Document  # noqa: F401
        from modules.student_leaves.models import StudentLeave  # noqa: F401
        from modules.announcements.models import (  # noqa: F401
            Announcement,
            AnnouncementRevision,
            AnnouncementAttachment,
        )
        from modules.academics.academic_year.models import AcademicYear
        from modules.academics.cycles.models import AcademicCycle  # noqa: F401
        from modules.examinations.models import (  # noqa: F401
            ExamMark,
            ExamPaper,
            ExamResult,
            ExamType,
            Examination,
            ExaminationLifecycleEvent,
            GradingBand,
            GradingScheme,
        )
        from modules.subjects.models import Subject
        from modules.streams.models import Stream  # noqa: F401
        from modules.departments.models import Department  # noqa: F401
        from modules.teachers.models import Teacher
        from modules.classes.models import Class, ClassSubject
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
        from modules.schedule.models import ScheduleOverride
        from modules.academics.calendar.holidays import Holiday
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
        from modules.hostel.models import (
            Hostel,
            HostelRoom,
            HostelBed,
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
