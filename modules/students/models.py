import enum

from shared.s3_utils import profile_picture_public_url
from sqlalchemy import text

from core.database import db
from core.models import TenantBaseModel
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

    student = db.relationship(
        "Student",
        backref=db.backref("documents", lazy=True),
        passive_deletes=True,
    )
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_user_id])

    def to_dict(self):
        """Serialize for API response. Do not expose direct S3 URLs — use view_url with auth."""
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
            "cloudinary_url": None,
            "view_url": f"/api/students/{self.student_id}/documents/{self.id}/file",
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

    # ---------------------------------------------------------------------
    # Extended profile fields (all optional; backward compatible)
    # ---------------------------------------------------------------------
    # Health / Physical
    blood_group = db.Column(db.String(10), nullable=True)
    height_cm = db.Column(db.Integer, nullable=True)
    weight_kg = db.Column(db.Numeric(6, 2), nullable=True)
    medical_allergies = db.Column(db.Text, nullable=True)
    medical_conditions = db.Column(db.Text, nullable=True)
    disability_details = db.Column(db.Text, nullable=True)
    identification_marks = db.Column(db.Text, nullable=True)

    # Parent / Family
    father_name = db.Column(db.String(120), nullable=True)
    father_phone = db.Column(db.String(20), nullable=True)
    father_email = db.Column(db.String(120), nullable=True)
    father_occupation = db.Column(db.String(120), nullable=True)
    father_annual_income = db.Column(db.Integer, nullable=True)

    mother_name = db.Column(db.String(120), nullable=True)
    mother_phone = db.Column(db.String(20), nullable=True)
    mother_email = db.Column(db.String(120), nullable=True)
    mother_occupation = db.Column(db.String(120), nullable=True)
    mother_annual_income = db.Column(db.Integer, nullable=True)

    guardian_address = db.Column(db.Text, nullable=True)
    guardian_occupation = db.Column(db.String(120), nullable=True)
    guardian_aadhar_number = db.Column(db.String(20), nullable=True)

    # Identity / Demographic
    aadhar_number = db.Column(db.String(20), nullable=True)
    apaar_id = db.Column(db.String(50), nullable=True)
    emis_number = db.Column(db.String(50), nullable=True)
    udise_student_id = db.Column(db.String(50), nullable=True)
    religion = db.Column(db.String(50), nullable=True)
    category = db.Column(db.String(50), nullable=True)
    caste = db.Column(db.String(50), nullable=True)
    nationality = db.Column(db.String(50), nullable=True)
    mother_tongue = db.Column(db.String(50), nullable=True)
    place_of_birth = db.Column(db.String(120), nullable=True)

    # Residence / Address
    current_address = db.Column(db.Text, nullable=True)
    current_city = db.Column(db.String(80), nullable=True)
    current_state = db.Column(db.String(80), nullable=True)
    current_pincode = db.Column(db.String(12), nullable=True)

    permanent_address = db.Column(db.Text, nullable=True)
    permanent_city = db.Column(db.String(80), nullable=True)
    permanent_state = db.Column(db.String(80), nullable=True)
    permanent_pincode = db.Column(db.String(12), nullable=True)

    is_same_as_permanent_address = db.Column(db.Boolean, nullable=True)
    is_commuting_from_outstation = db.Column(db.Boolean, nullable=True)
    commute_location = db.Column(db.String(120), nullable=True)
    commute_notes = db.Column(db.Text, nullable=True)

    # Emergency
    emergency_contact_name = db.Column(db.String(120), nullable=True)
    emergency_contact_relationship = db.Column(db.String(50), nullable=True)
    emergency_contact_phone = db.Column(db.String(20), nullable=True)
    emergency_contact_alt_phone = db.Column(db.String(20), nullable=True)

    # Academic / School internal
    admission_date = db.Column(db.Date, nullable=True)
    previous_school_name = db.Column(db.String(255), nullable=True)
    previous_school_class = db.Column(db.String(50), nullable=True)
    last_school_board = db.Column(db.String(100), nullable=True)
    tc_number = db.Column(db.String(50), nullable=True)
    house_name = db.Column(db.String(50), nullable=True)
    student_status = db.Column(db.String(30), nullable=True)

    is_transport_opted = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

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
    
    def to_dict(self, include_profile_picture: bool = True):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.user.name if self.user else None,
            "email": self.user.email if self.user else None,
            # `profile_picture` resolves to a presigned S3 URL, which is
            # expensive to generate in bulk. Skip it on list endpoints.
            "profile_picture": (
                profile_picture_public_url(self.user.profile_picture_url)
                if (include_profile_picture and self.user)
                else None
            ),
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
            # Extended profile fields
            "blood_group": self.blood_group,
            "height_cm": self.height_cm,
            "weight_kg": float(self.weight_kg) if self.weight_kg is not None else None,
            "medical_allergies": self.medical_allergies,
            "medical_conditions": self.medical_conditions,
            "disability_details": self.disability_details,
            "identification_marks": self.identification_marks,

            "father_name": self.father_name,
            "father_phone": self.father_phone,
            "father_email": self.father_email,
            "father_occupation": self.father_occupation,
            "father_annual_income": self.father_annual_income,

            "mother_name": self.mother_name,
            "mother_phone": self.mother_phone,
            "mother_email": self.mother_email,
            "mother_occupation": self.mother_occupation,
            "mother_annual_income": self.mother_annual_income,

            "guardian_address": self.guardian_address,
            "guardian_occupation": self.guardian_occupation,
            "guardian_aadhar_number": self.guardian_aadhar_number,

            "aadhar_number": self.aadhar_number,
            "apaar_id": self.apaar_id,
            "emis_number": self.emis_number,
            "udise_student_id": self.udise_student_id,
            "religion": self.religion,
            "category": self.category,
            "caste": self.caste,
            "nationality": self.nationality,
            "mother_tongue": self.mother_tongue,
            "place_of_birth": self.place_of_birth,

            "current_address": self.current_address,
            "current_city": self.current_city,
            "current_state": self.current_state,
            "current_pincode": self.current_pincode,

            "permanent_address": self.permanent_address,
            "permanent_city": self.permanent_city,
            "permanent_state": self.permanent_state,
            "permanent_pincode": self.permanent_pincode,

            "is_same_as_permanent_address": self.is_same_as_permanent_address,
            "is_commuting_from_outstation": self.is_commuting_from_outstation,
            "commute_location": self.commute_location,
            "commute_notes": self.commute_notes,

            "emergency_contact_name": self.emergency_contact_name,
            "emergency_contact_relationship": self.emergency_contact_relationship,
            "emergency_contact_phone": self.emergency_contact_phone,
            "emergency_contact_alt_phone": self.emergency_contact_alt_phone,

            "admission_date": self.admission_date.isoformat() if self.admission_date else None,
            "previous_school_name": self.previous_school_name,
            "previous_school_class": self.previous_school_class,
            "last_school_board": self.last_school_board,
            "tc_number": self.tc_number,
            "house_name": self.house_name,
            "student_status": self.student_status,
            "is_transport_opted": bool(self.is_transport_opted),
            "created_at": self.created_at.isoformat()
        }

    def __repr__(self):
        return f"<Student {self.admission_number}>"
