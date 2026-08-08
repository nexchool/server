"""Finance tasks - overdue fee processing (idempotent)."""

from datetime import date

from celery_app import get_celery

celery_app = get_celery()


@celery_app.task(bind=True, name="process_overdue_fees_task")
def process_overdue_fees_task(self):
    """
    Process overdue student fees. Idempotent:
    - Only change status if not already 'overdue'.
    - Only send notification when status changes.
    Runs with Flask app context (ContextTask).
    """
    from core.database import db
    from modules.finance.models import StudentFee
    from modules.finance.enums import StudentFeeStatus
    from modules.notifications.services import notification_dispatcher
    from modules.notifications.enums import NotificationChannel, NotificationType

    today = date.today()
    changed_count = 0

    # Deliberately every tenant: this job ages fees for the whole platform.
    # Note the scope is not merely absent here, it CANNOT apply — the listener
    # in core/database.py returns early without a request context, so a worker
    # query is never tenant-filtered. Any job that must stay within one tenant
    # has to say so itself.
    query = db.session.query(StudentFee).filter(
        StudentFee.status != StudentFeeStatus.paid.value,
        StudentFee.due_date < today,
    )

    for sf in query.all():
        # Idempotent: only change if not already overdue
        if sf.status == StudentFeeStatus.overdue.value:
            continue

        old_status = sf.status
        sf.status = StudentFeeStatus.overdue.value
        db.session.add(sf)
        changed_count += 1

        # Only send notification when status changes to overdue
        student = sf.student
        if student and student.user_id:
            notification_dispatcher.dispatch(
                user_id=student.user_id,
                tenant_id=sf.tenant_id,
                notification_type=NotificationType.FEE_OVERDUE.value,
                channels=[
                    NotificationChannel.IN_APP.value,
                    NotificationChannel.EMAIL.value,
                    NotificationChannel.PUSH.value,
                ],
                title="Fee Overdue",
                body=f"Your fee (due {sf.due_date}) is now overdue. Please pay at the earliest.",
                extra_data={
                    "student_fee_id": sf.id,
                    "due_date": sf.due_date.isoformat() if sf.due_date else None,
                    "total_amount": float(sf.total_amount) if sf.total_amount else None,
                },
            )

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {"changed_count": changed_count}
