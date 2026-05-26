"""Subject template models for setup wizard Step 0 (school type selection)."""

from datetime import datetime, timezone
import uuid

from core.database import db


class SubjectTemplateGroup(db.Model):
    """One template per board: CBSE, ICSE, Gujarat State Board, IB, Custom."""

    __tablename__ = "subject_template_groups"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    board_code = db.Column(
        db.String(30), nullable=False, unique=True, index=True
    )  # 'cbse', 'icse', 'gujarat_state_board', 'ib', 'custom'
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    items = db.relationship(
        "SubjectTemplateItem",
        back_populates="group",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="SubjectTemplateItem.grade_number, SubjectTemplateItem.sort_order",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "board_code": self.board_code,
            "is_active": self.is_active,
        }


class SubjectTemplateItem(db.Model):
    """One subject row per grade in a template. Includes stream for Grade 11-12."""

    __tablename__ = "subject_template_items"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    template_group_id = db.Column(
        db.String(36),
        db.ForeignKey("subject_template_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grade_number = db.Column(db.Integer, nullable=False)
    stream = db.Column(
        db.String(32),
        nullable=True,
        comment="NULL = all streams (Grade 1-10). Science/Commerce/Arts/Vocational for Grade 11-12.",
    )
    subject_name = db.Column(db.String(100), nullable=False)
    subject_code = db.Column(db.String(20), nullable=True)
    periods_per_week = db.Column(db.Integer, nullable=True, default=5)
    is_elective = db.Column(db.Boolean, nullable=False, default=False)
    role = db.Column(
        db.String(32),
        nullable=True,
        comment="first_language | second_language | third_language | core | elective | co_curricular",
    )
    medium = db.Column(
        db.String(16),
        nullable=True,
        comment="english | gujarati — default medium implied by the template's board (informational on the item).",
    )
    elective_group_key = db.Column(
        db.String(80),
        nullable=True,
        comment="Items sharing this key are pick-one alternatives (e.g. Hindi vs Sanskrit at Std 9 third language).",
    )
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    group = db.relationship("SubjectTemplateGroup", back_populates="items")

    def to_dict(self):
        return {
            "id": self.id,
            "template_group_id": self.template_group_id,
            "grade_number": self.grade_number,
            "stream": self.stream,
            "subject_name": self.subject_name,
            "subject_code": self.subject_code,
            "periods_per_week": self.periods_per_week,
            "is_elective": self.is_elective,
            "role": self.role,
            "medium": self.medium,
            "elective_group_key": self.elective_group_key,
            "sort_order": self.sort_order,
        }
