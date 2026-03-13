import enum
from backend.core.database import db
from backend.core.models import TenantBaseModel
from datetime import datetime
import uuid


# Document type labels for API responses
DOCUMENT_TYPE_LABELS = {
    "aadhar_card": "Aadhar Card",
    "birth_certificate": "Birth Certificate",
    "leaving_certificate": "Leaving Certificate",
    "transfer_certificate": "Transfer Certificate",
    "passport": "Passport",
    "other": "Other",
}


class DocumentType(enum.Enum):
    """Document types for student documents."""

    AADHAR_CARD = "aadhar_card"
    BIRTH_CERTIFICATE = "birth_certificate"
    LEAVING_CERTIFICATE = "leaving_certificate"
    TRANSFER_CERTIFICATE = "transfer_certificate"
    PASSPORT = "passport"
    OTHER = "other"


class StudentDocument(TenantBaseModel):
    """
    Student document model for storing PDF/image documents.

    Files are uploaded to Cloudinary; this model stores metadata.
    Scoped by tenant. Extends TenantBaseModel (tenant_id).
    """

    __tablename__ = "student_documents"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = db.Column(
        db.String(36),
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type = db.Column(
        db.Enum(DocumentType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    original_filename = db.Column(db.String(255), nullable=False)
    cloudinary_url = db.Column(db.Text, nullable=False)
    cloudinary_public_id = db.Column(db.String(500), nullable=False, unique=True)
    mime_type = db.Column(db.String(100), nullable=False)
    file_size_bytes = db.Column(db.Integer, nullable=False)
    uploaded_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    student = db.relationship("Student", backref=db.backref("documents", lazy=True))
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_user_id])

    def to_dict(self):
        """Serialize for API response."""
        return {
            "id": self.id,
            "student_id": self.student_id,
            "document_type": self.document_type.value if self.document_type else None,
            "document_type_label": DOCUMENT_TYPE_LABELS.get(
                self.document_type.value, self.document_type.value
            )
            if self.document_type
            else None,
            "original_filename": self.original_filename,
            "cloudinary_url": self.cloudinary_url,
            "mime_type": self.mime_type,
            "file_size_bytes": self.file_size_bytes,
            "uploaded_by": {
                "id": self.uploaded_by.id,
                "name": self.uploaded_by.name or "",
            }
            if self.uploaded_by
            else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Student(TenantBaseModel):
    """
    Student Model
    
    Extends the User model with student-specific data.
    Linked to a Class. Scoped by tenant.
    """
    __tablename__ = "students"
    __table_args__ = (
        db.UniqueConstraint("admission_number", "tenant_id", name="uq_students_admission_number_tenant"),
        db.UniqueConstraint("user_id", "tenant_id", name="uq_students_user_id_tenant"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Link to Auth User (One-to-One)
    # The User record handles email, password, name, profile pic
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)

    # Academic Info
    admission_number = db.Column(db.String(20), nullable=False, index=True)
    roll_number = db.Column(db.Integer, nullable=True)
    academic_year = db.Column(db.String(20), nullable=True)  # Deprecated; use academic_year_id
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Current Class Assignment
    class_id = db.Column(db.String(36), db.ForeignKey('classes.id'), nullable=True)
    
    # Personal Info
    date_of_birth = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(10), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.Text, nullable=True)
    
    # Guardian Info
    guardian_name = db.Column(db.String(100), nullable=True)
    guardian_relationship = db.Column(db.String(50), nullable=True)
    guardian_phone = db.Column(db.String(20), nullable=True)
    guardian_email = db.Column(db.String(120), nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    # Access user fields via student.user.email etc.
    user = db.relationship('User', backref=db.backref('student_profile', uselist=False))
    
    # Access class info via student.current_class.name
    current_class = db.relationship('Class', backref=db.backref('students', lazy=True))
    academic_year_ref = db.relationship(
        "AcademicYear",
        foreign_keys=[academic_year_id],
        lazy=True,
    )

    def save(self):
        db.session.add(self)
        db.session.commit()
    
    def delete(self):
        db.session.delete(self)
        db.session.commit()
    
    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.user.name if self.user else None,
            "email": self.user.email if self.user else None,
            "profile_picture": self.user.profile_picture_url if self.user else None,
            "admission_number": self.admission_number,
            "roll_number": self.roll_number,
            "academic_year": self.academic_year_ref.name if self.academic_year_ref else self.academic_year,
            "academic_year_id": self.academic_year_id,
            "class_id": self.class_id,
            "class_name": f"{self.current_class.name}-{self.current_class.section}" if self.current_class else None,
            "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "gender": self.gender,
            "phone": self.phone,
            "address": self.address,
            "guardian_name": self.guardian_name,
            "guardian_relationship": self.guardian_relationship,
            "guardian_phone": self.guardian_phone,
            "guardian_email": self.guardian_email,
            "created_at": self.created_at.isoformat()
        }

    def __repr__(self):
        return f"<Student {self.admission_number}>"
