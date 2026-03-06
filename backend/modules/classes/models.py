from backend.core.database import db
from backend.core.models import TenantBaseModel
from datetime import datetime
import uuid


class Class(TenantBaseModel):
    """
    Class/Section Model

    Represents a specific class division (e.g., Grade 10-A) for an academic year.
    Students are assigned to a Class.
    A Teacher is assigned as the class teacher. Scoped by tenant.
    """
    __tablename__ = "classes"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(50), nullable=False)  # e.g. "Grade 10"
    section = db.Column(db.String(10), nullable=False)  # e.g. "A"
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Academic year date bounds
    start_date = db.Column(db.Date, nullable=True)  # e.g. 2025-06-01
    end_date = db.Column(db.Date, nullable=True)     # e.g. 2026-03-31

    # Class Teacher (User with Teacher role)
    teacher_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "name", "section", "academic_year_id", "tenant_id",
            name="uq_class_section_academic_year_id_tenant",
        ),
        # One teacher can only be class teacher of one class per tenant
        db.UniqueConstraint(
            "teacher_id", "tenant_id",
            name="uq_classes_teacher_id_tenant",
        ),
    )

    # Relationships
    teacher = db.relationship('User', foreign_keys=[teacher_id], backref=db.backref('assigned_classes', lazy=True))
    academic_year_ref = db.relationship(
        "AcademicYear",
        foreign_keys=[academic_year_id],
        lazy=True,
    )

    def save(self):
        db.session.add(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "section": self.section,
            "academic_year": self.academic_year_ref.name if self.academic_year_ref else None,
            "academic_year_id": self.academic_year_id,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "teacher_id": self.teacher_id,
            "teacher_name": self.teacher.name if self.teacher else None,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self):
        return f"<Class {self.name}-{self.section} ({self.academic_year_ref.name if self.academic_year_ref else None})>"


class ClassTeacher(TenantBaseModel):
    """
    Class-Teacher Junction Table

    Maps teachers to classes they teach. A teacher can be assigned to multiple classes,
    and a class can have multiple teachers (for different subjects). Scoped by tenant.
    """
    __tablename__ = "class_teachers"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    class_id = db.Column(db.String(36), db.ForeignKey("classes.id"), nullable=False)
    teacher_id = db.Column(db.String(36), db.ForeignKey("teachers.id"), nullable=False)
    subject = db.Column(db.String(100), nullable=True)  # What subject the teacher teaches in this class
    is_class_teacher = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "class_id", "teacher_id", "tenant_id",
            name="uq_class_teacher_tenant",
        ),
    )

    # Relationships
    class_ref = db.relationship('Class', backref=db.backref('class_teachers', lazy=True))
    teacher = db.relationship('Teacher', backref=db.backref('class_assignments', lazy=True))

    def save(self):
        db.session.add(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "class_id": self.class_id,
            "teacher_id": self.teacher_id,
            "teacher_name": self.teacher.user.name if self.teacher and self.teacher.user else None,
            "teacher_employee_id": self.teacher.employee_id if self.teacher else None,
            "subject": self.subject,
            "is_class_teacher": self.is_class_teacher,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self):
        return f"<ClassTeacher class={self.class_id} teacher={self.teacher_id}>"
