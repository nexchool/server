"""Finance tasks - overdue fee processing (idempotent)."""

from datetime import date

from backend.celery_app import get_celery

celery_app = get_celery()


@celery_app.task(bind=True, name="process_overdue_fees_task")
def process_overdue_fees_task(self):
    """
    Process overdue student fees. Idempotent:
    - Only change status if not already 'overdue'.
    - Only send notification when status changes.
    Runs with Flask app context (ContextTask).
    """
    from backend.core.database import db
    from backend.modules.finance.models import StudentFee
    from backend.modules.finance.enums import StudentFeeStatus
    from backend.modules.notifications.services import notification_dispatcher
    from backend.modules.notifications.enums import NotificationChannel, NotificationType

    today = date.today()
    changed_count = 0

    # StudentFee is tenant-scoped; without request context, query all overdue
    # (tenant filter is via __tenant_scoped__ which uses g.tenant_id - not set in worker)
    # So we must filter by tenant explicitly. Get all unpaid/partial with due_date < today
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
                channels=[NotificationChannel.IN_APP.value, NotificationChannel.EMAIL.value],
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
