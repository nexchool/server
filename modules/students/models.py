import enum

from shared.s3_utils import profile_picture_public_url
from sqlalchemy import text

from core.database import db
from core.models import TenantBaseModel
from datetime import datetime
import uuid
from core.school_time import utc_now


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

    Files are uploaded to AWS S3; this model stores metadata (the object key).
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
    # S3 object key / resolvable URL for the stored file.
    file_url = db.Column(db.Text, nullable=False)
    s3_object_key = db.Column(db.String(500), nullable=False, unique=True)
    mime_type = db.Column(db.String(100), nullable=False)
    file_size_bytes = db.Column(db.Integer, nullable=False)
    uploaded_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utc_now, onupdate=utc_now
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
            "file_url": None,
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

    # The account behind this student, when the school has issued one.
    # Optional (ADR-003): a student exists without a login; migration 094.
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)

    # The human this student relationship belongs to (ADR-001). Nullable until
    # the People backfill has run; the identity columns below move to Person and
    # are dropped in a later cleanup migration.
    person_id = db.Column(
        db.String(36),
        db.ForeignKey("persons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Declared from this side so People can see that a person studies here
    # without importing this module.
    person = db.relationship(
        "Person",
        foreign_keys=[person_id],
        backref=db.backref("student_relationships", lazy=True),
    )

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
    
    # Personal identity — date of birth, gender, phone, address and Aadhaar —
    # belongs to the Person (ADR-001) and was dropped from here in migration
    # 090. The family columns below stay until the household read moves.

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
    # Year-end / promotion eligibility (e.g. pass, fail); optional.
    academic_result = db.Column(db.String(20), nullable=True)

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
    
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

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
    
    def _class_display_name(self):
        """Class label for payloads. Class.name is a legacy nullable display
        column — grade-based classes (post multi-school migration) carry their
        label on grade.name, so coalesce before joining with the section."""
        c = self.current_class
        if not c:
            return None
        label = c.name or (c.grade.name if c.grade else None)
        return "-".join(p for p in (label, c.section) if p) or None

    def to_dict(self, include_profile_picture: bool = True,
                include_family: bool = True):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.person.full_name if self.person else None,
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
            "class_name": self._class_display_name(),
            "programme_id": self.current_class.programme_id if self.current_class else None,
            "programme_name": (
                self.current_class.programme.name
                if self.current_class and self.current_class.programme
                else None
            ),
            # Who this student is comes from their Person (ADR-001). The
            # columns below are the same facts left over from before People
            # existed, and are dropped once nothing reads them. The family
            # fields further down still read these columns — see the migration
            # debt register for why they are cut over with the client, not here.
            "date_of_birth": (
                self.person.date_of_birth.isoformat()
                if self.person and self.person.date_of_birth
                else None
            ),
            "gender": self.person.gender if self.person else None,
            "phone": self.person.phone_number if self.person else None,
            "address": self.person.address if self.person else None,
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

            "aadhar_number": self.person.aadhaar_number if self.person else None,
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
            "academic_result": self.academic_result,
            "is_transport_opted": bool(self.is_transport_opted),
            # The household as it actually is (ADR-002): every responsible
            # adult, each with their relationship, and which one the school
            # calls. The flat father_/mother_/guardian_ keys above say the same
            # thing in v1's shape and stay until the mobile client moves.
            "family": self._household() if include_family else None,
            "created_at": self.created_at.isoformat()
        }

    def _household(self):
        """The household, read through relationships the caller must have
        loaded. A list endpoint asks for this per row otherwise, which is four
        queries a student — see the guard in test_students_list_queries.
        """
        from modules.people.relationships import household_of

        return [
            {
                "person_id": member.person_id,
                "name": member.person.full_name,
                "relationship": member.relationship,
                "phone": member.person.phone_number,
                "email": member.person.email,
                "occupation": member.person.occupation,
                "is_primary_contact": member.is_primary_contact,
            }
            for member in household_of(self.person)
        ]

    def __repr__(self):
        return f"<Student {self.admission_number}>"


class StudentPromotionBatch(TenantBaseModel):
    """Audit row for an academic-year promotion run (batch log)."""

    __tablename__ = "student_promotion_batches"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    from_academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="SET NULL"),
        nullable=False,
        index=True,
    )
    to_academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="SET NULL"),
        nullable=False,
        index=True,
    )
    status = db.Column(db.String(20), nullable=False)  # completed | failed
    summary = db.Column(db.JSON, nullable=True)
    class_mapping_snapshot = db.Column(db.JSON, nullable=True)
    created_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    def to_dict(self):
        return {
            "id": self.id,
            "from_academic_year_id": self.from_academic_year_id,
            "to_academic_year_id": self.to_academic_year_id,
            "status": self.status,
            "summary": self.summary,
            "created_by_user_id": self.created_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# Business events in a student's life, in the canon's vocabulary
# (docs/architecture/business-events.md). Two domains write these: Student
# Management owns admission, withdrawal and return; Academic owns placement,
# transfer, promotion and graduation. The timeline is one list because a
# school reads a student's history as one story.
EVENT_ADMITTED = "StudentAdmitted"
EVENT_ENROLLED = "AcademicEnrollmentCreated"
EVENT_SECTION_TRANSFERRED = "SectionTransferred"
EVENT_PROMOTED = "PromotionCompleted"
EVENT_WITHDRAWN = "StudentWithdrawn"
EVENT_RE_ENROLLED = "StudentReEnrolled"
EVENT_GRADUATED = "StudentGraduated"


class StudentLifecycleEvent(TenantBaseModel):
    """A milestone in one student's time at the school.

    Written because the records cannot answer these questions on their own.
    Enrollments say where a student sat and when it ended; they do not say
    whether the year ended in a graduation, a withdrawal or a family moving
    town — and until now the only trace of a status change was that
    `students.updated_at` moved.

    The alternative was a column per outcome on `students` — withdrawn_on,
    withdrawal_reason, graduated_on — which is how a table stops describing
    a student and starts describing a workflow.

    Rows are never edited. A correction is a new event; the school's history
    is what happened, including what was recorded and later reconsidered.
    """

    __tablename__ = "student_lifecycle_events"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = db.Column(
        db.String(36),
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event = db.Column(db.String(40), nullable=False)
    # The date the school would put on it, which is not always today: a
    # withdrawal is often recorded after the family has already gone.
    occurred_on = db.Column(db.Date, nullable=False)
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reason = db.Column(db.Text, nullable=True)
    # Whatever the workflow knows that a later reader would want: the class
    # left, the grade completed, the batch a promotion belonged to.
    details = db.Column(db.JSON, nullable=True)
    recorded_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "event": self.event,
            "occurred_on": self.occurred_on.isoformat() if self.occurred_on else None,
            "academic_year_id": self.academic_year_id,
            "reason": self.reason,
            "details": self.details,
            "recorded_by_user_id": self.recorded_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<StudentLifecycleEvent {self.event} student={self.student_id}>"
