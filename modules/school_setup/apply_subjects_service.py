"""Apply subject offerings service.

Seeds class_subjects linking every active Subject to every Class in the given
academic year for a tenant. Additive and idempotent — never overwrites or
removes existing rows.
"""

from core.database import db
from modules.classes.models import Class, ClassSubject
from modules.subjects.models import Subject


DEFAULT_WEEKLY_PERIODS = 5


def apply_subject_offerings(*, tenant_id: str, academic_year_id: str) -> dict:
    """Seed class_subjects for every (active) Class × Subject in the tenant.

    Additive only — never overwrites or replaces existing class_subjects.
    Returns {"created": n, "skipped": m}.
    """
    classes = Class.query.filter_by(
        tenant_id=tenant_id, academic_year_id=academic_year_id
    ).all()
    subjects = Subject.query.filter_by(tenant_id=tenant_id, is_active=True).all()
    if not classes or not subjects:
        return {"created": 0, "skipped": 0}

    existing_pairs = {
        (cs.class_id, cs.subject_id)
        for cs in ClassSubject.query.filter(
            ClassSubject.class_id.in_([c.id for c in classes])
        ).all()
    }
    created = 0
    skipped = 0
    for c in classes:
        for s in subjects:
            if (c.id, s.id) in existing_pairs:
                skipped += 1
                continue
            cs = ClassSubject(
                tenant_id=tenant_id,
                class_id=c.id,
                subject_id=s.id,
                weekly_periods=DEFAULT_WEEKLY_PERIODS,
            )
            db.session.add(cs)
            created += 1
    db.session.commit()
    return {"created": created, "skipped": skipped}
