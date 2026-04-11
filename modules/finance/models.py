"""
Finance Module Models

SQLAlchemy models for fee collection: FeeStructure, FeeComponent,
StudentFee, StudentFeeItem, Payment. Uses TenantBaseModel for tenant_id filtering.
AcademicYear lives in academics module; finance consumes via FK only.
"""

from datetime import datetime
import uuid

from sqlalchemy import text

from core.database import db
from core.models import TenantBaseModel

from .enums import StudentFeeStatus, PaymentStatus, PaymentMethod


class FeeStructureClass(TenantBaseModel):
    """Junction: fee structure <-> class (many-to-many). One structure can apply to multiple classes."""
    __tablename__ = "fee_structure_classes"
    __table_args__ = (
        db.UniqueConstraint(
            "academic_year_id", "class_id", "tenant_id",
            name="uq_fee_structure_classes_year_class_tenant",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fee_structure_id = db.Column(
        db.String(36),
        db.ForeignKey("fee_structures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    class_id = db.Column(
        db.String(36),
        db.ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    fee_structure = db.relationship("FeeStructure", backref=db.backref("structure_classes", lazy=True))
    class_ref = db.relationship("Class", backref=db.backref("fee_structure_classes", lazy=True))


class FeeStructure(TenantBaseModel):
    """
    Fee Structure Model.

    A fee structure groups fee components for an academic year.
    Optionally scoped to a class (class_id nullable = applies to all).
    Scoped by tenant.
    """
    __tablename__ = "fee_structures"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(100), nullable=False, index=True)
    is_transport_only = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    due_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    components = db.relationship(
        "FeeComponent",
        backref=db.backref("fee_structure", lazy=True),
        order_by="FeeComponent.sort_order, FeeComponent.created_at",
    )
    student_fees = db.relationship("StudentFee", backref=db.backref("fee_structure", lazy=True))
    academic_year = db.relationship(
        "AcademicYear",
        foreign_keys=[academic_year_id],
        lazy=True,
    )

    @property
    def class_ids(self):
        return [sc.class_id for sc in self.structure_classes]

    @property
    def class_names(self):
        return [
            f"{sc.class_ref.name}-{sc.class_ref.section}" if sc.class_ref else None
            for sc in self.structure_classes
        ]

    def to_dict(self):
        class_ids = self.class_ids
        class_names = self.class_names
        return {
            "id": self.id,
            "academic_year_id": self.academic_year_id,
            "name": self.name,
            "is_transport_only": bool(self.is_transport_only),
            "class_id": class_ids[0] if len(class_ids) == 1 else None,
            "class_ids": class_ids,
            "class_name": ", ".join(n for n in class_names if n) if class_names else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<FeeStructure {self.name}>"


class FeeComponent(TenantBaseModel):
    """
    Fee Component Model.

    Individual fee line item within a fee structure (e.g., Tuition, Library, Lab).
    Scoped by tenant.
    """
    __tablename__ = "fee_components"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fee_structure_id = db.Column(
        db.String(36),
        db.ForeignKey("fee_structures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    is_optional = db.Column(db.Boolean, nullable=False, default=False, server_default=text("false"))
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "fee_structure_id": self.fee_structure_id,
            "name": self.name,
            "amount": float(self.amount) if self.amount is not None else None,
            "is_optional": self.is_optional,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<FeeComponent {self.name}>"


class StudentFee(TenantBaseModel):
    """
    Student Fee Model.

    Links a student to a fee structure. Tracks total, paid amount, and status.
    Scoped by tenant.
    """
    __tablename__ = "student_fees"
    __table_args__ = (
        db.UniqueConstraint(
            "student_id", "fee_structure_id", "tenant_id",
            name="uq_student_fees_student_structure_tenant",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = db.Column(
        db.String(36),
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fee_structure_id = db.Column(
        db.String(36),
        db.ForeignKey("fee_structures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default=StudentFeeStatus.unpaid.value,
        index=True,
    )
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default="0")
    due_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # passive_deletes: rely on DB FK ON DELETE CASCADE; ORM must not null student_id first (NOT NULL).
    student = db.relationship(
        "Student",
        backref=db.backref("student_fees", lazy=True),
        passive_deletes=True,
    )
    items = db.relationship(
        "StudentFeeItem",
        backref=db.backref("student_fee", lazy=True),
        order_by="StudentFeeItem.created_at",
    )
    payments = db.relationship(
        "Payment",
        backref=db.backref("student_fee", lazy=True),
        order_by="Payment.created_at.desc()",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "fee_structure_id": self.fee_structure_id,
            "status": self.status,
            "total_amount": float(self.total_amount) if self.total_amount is not None else None,
            "paid_amount": float(self.paid_amount) if self.paid_amount is not None else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<StudentFee student={self.student_id} status={self.status}>"


class StudentFeeItem(TenantBaseModel):
    """
    Student Fee Item Model.

    Per-component breakdown for a student fee. Tracks amount and paid_amount per component.
    Scoped by tenant.
    """
    __tablename__ = "student_fee_items"
    __table_args__ = (
        db.UniqueConstraint(
            "student_fee_id", "fee_component_id", "tenant_id",
            name="uq_student_fee_items_fee_component_tenant",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_fee_id = db.Column(
        db.String(36),
        db.ForeignKey("student_fees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fee_component_id = db.Column(
        db.String(36),
        db.ForeignKey("fee_components.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    fee_component = db.relationship("FeeComponent", backref=db.backref("student_fee_items", lazy=True))

    def to_dict(self):
        return {
            "id": self.id,
            "student_fee_id": self.student_fee_id,
            "fee_component_id": self.fee_component_id,
            "component_name": self.fee_component.name if self.fee_component else None,
            "amount": float(self.amount) if self.amount is not None else None,
            "paid_amount": float(self.paid_amount) if self.paid_amount is not None else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<StudentFeeItem fee={self.student_fee_id} component={self.fee_component_id}>"


class Payment(TenantBaseModel):
    """
    Payment Model.

    Records a payment toward a student fee. Method, status, reference.
    Scoped by tenant.
    """
    __tablename__ = "payments"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_fee_id = db.Column(
        db.String(36),
        db.ForeignKey("student_fees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(20), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=PaymentStatus.success.value, index=True)
    reference_number = db.Column(db.String(100), nullable=True, index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by_user = db.relationship("User", backref=db.backref("payments_created", lazy=True))

    def to_dict(self):
        return {
            "id": self.id,
            "student_fee_id": self.student_fee_id,
            "amount": float(self.amount) if self.amount is not None else None,
            "method": self.method,
            "status": self.status,
            "reference_number": self.reference_number,
            "notes": self.notes,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<Payment {self.id} amount={self.amount} status={self.status}>"
