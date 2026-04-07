"""Add extended student profile fields (health/identity/residence/emergency/academic).

Revision ID: 025_student_ext_profile
Revises: 024_class_grade_level
Create Date: 2026-04-07
"""

from alembic import op
import sqlalchemy as sa


revision = "025_student_ext_profile"
down_revision = "024_class_grade_level"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Health / Physical
    op.add_column("students", sa.Column("blood_group", sa.String(10), nullable=True))
    op.add_column("students", sa.Column("height_cm", sa.Integer(), nullable=True))
    op.add_column("students", sa.Column("weight_kg", sa.Numeric(6, 2), nullable=True))
    op.add_column("students", sa.Column("medical_allergies", sa.Text(), nullable=True))
    op.add_column("students", sa.Column("medical_conditions", sa.Text(), nullable=True))
    op.add_column("students", sa.Column("disability_details", sa.Text(), nullable=True))
    op.add_column("students", sa.Column("identification_marks", sa.Text(), nullable=True))

    # Parent / Family
    op.add_column("students", sa.Column("father_name", sa.String(120), nullable=True))
    op.add_column("students", sa.Column("father_phone", sa.String(20), nullable=True))
    op.add_column("students", sa.Column("father_email", sa.String(120), nullable=True))
    op.add_column("students", sa.Column("father_occupation", sa.String(120), nullable=True))
    op.add_column("students", sa.Column("father_annual_income", sa.Integer(), nullable=True))

    op.add_column("students", sa.Column("mother_name", sa.String(120), nullable=True))
    op.add_column("students", sa.Column("mother_phone", sa.String(20), nullable=True))
    op.add_column("students", sa.Column("mother_email", sa.String(120), nullable=True))
    op.add_column("students", sa.Column("mother_occupation", sa.String(120), nullable=True))
    op.add_column("students", sa.Column("mother_annual_income", sa.Integer(), nullable=True))

    op.add_column("students", sa.Column("guardian_address", sa.Text(), nullable=True))
    op.add_column("students", sa.Column("guardian_occupation", sa.String(120), nullable=True))
    op.add_column("students", sa.Column("guardian_aadhar_number", sa.String(20), nullable=True))

    # Identity / Demographic
    op.add_column("students", sa.Column("aadhar_number", sa.String(20), nullable=True))
    op.add_column("students", sa.Column("apaar_id", sa.String(50), nullable=True))
    op.add_column("students", sa.Column("emis_number", sa.String(50), nullable=True))
    op.add_column("students", sa.Column("udise_student_id", sa.String(50), nullable=True))
    op.add_column("students", sa.Column("religion", sa.String(50), nullable=True))
    op.add_column("students", sa.Column("category", sa.String(50), nullable=True))
    op.add_column("students", sa.Column("caste", sa.String(50), nullable=True))
    op.add_column("students", sa.Column("nationality", sa.String(50), nullable=True))
    op.add_column("students", sa.Column("mother_tongue", sa.String(50), nullable=True))
    op.add_column("students", sa.Column("place_of_birth", sa.String(120), nullable=True))

    # Residence / Address
    op.add_column("students", sa.Column("current_address", sa.Text(), nullable=True))
    op.add_column("students", sa.Column("current_city", sa.String(80), nullable=True))
    op.add_column("students", sa.Column("current_state", sa.String(80), nullable=True))
    op.add_column("students", sa.Column("current_pincode", sa.String(12), nullable=True))

    op.add_column("students", sa.Column("permanent_address", sa.Text(), nullable=True))
    op.add_column("students", sa.Column("permanent_city", sa.String(80), nullable=True))
    op.add_column("students", sa.Column("permanent_state", sa.String(80), nullable=True))
    op.add_column("students", sa.Column("permanent_pincode", sa.String(12), nullable=True))

    op.add_column("students", sa.Column("is_same_as_permanent_address", sa.Boolean(), nullable=True))
    op.add_column("students", sa.Column("is_commuting_from_outstation", sa.Boolean(), nullable=True))
    op.add_column("students", sa.Column("commute_location", sa.String(120), nullable=True))
    op.add_column("students", sa.Column("commute_notes", sa.Text(), nullable=True))

    # Emergency
    op.add_column("students", sa.Column("emergency_contact_name", sa.String(120), nullable=True))
    op.add_column("students", sa.Column("emergency_contact_relationship", sa.String(50), nullable=True))
    op.add_column("students", sa.Column("emergency_contact_phone", sa.String(20), nullable=True))
    op.add_column("students", sa.Column("emergency_contact_alt_phone", sa.String(20), nullable=True))

    # Academic / School internal
    op.add_column("students", sa.Column("admission_date", sa.Date(), nullable=True))
    op.add_column("students", sa.Column("previous_school_name", sa.String(255), nullable=True))
    op.add_column("students", sa.Column("previous_school_class", sa.String(50), nullable=True))
    op.add_column("students", sa.Column("last_school_board", sa.String(100), nullable=True))
    op.add_column("students", sa.Column("tc_number", sa.String(50), nullable=True))
    op.add_column("students", sa.Column("house_name", sa.String(50), nullable=True))
    op.add_column("students", sa.Column("student_status", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("students", "student_status")
    op.drop_column("students", "house_name")
    op.drop_column("students", "tc_number")
    op.drop_column("students", "last_school_board")
    op.drop_column("students", "previous_school_class")
    op.drop_column("students", "previous_school_name")
    op.drop_column("students", "admission_date")

    op.drop_column("students", "emergency_contact_alt_phone")
    op.drop_column("students", "emergency_contact_phone")
    op.drop_column("students", "emergency_contact_relationship")
    op.drop_column("students", "emergency_contact_name")

    op.drop_column("students", "commute_notes")
    op.drop_column("students", "commute_location")
    op.drop_column("students", "is_commuting_from_outstation")
    op.drop_column("students", "is_same_as_permanent_address")
    op.drop_column("students", "permanent_pincode")
    op.drop_column("students", "permanent_state")
    op.drop_column("students", "permanent_city")
    op.drop_column("students", "permanent_address")
    op.drop_column("students", "current_pincode")
    op.drop_column("students", "current_state")
    op.drop_column("students", "current_city")
    op.drop_column("students", "current_address")

    op.drop_column("students", "place_of_birth")
    op.drop_column("students", "mother_tongue")
    op.drop_column("students", "nationality")
    op.drop_column("students", "caste")
    op.drop_column("students", "category")
    op.drop_column("students", "religion")
    op.drop_column("students", "udise_student_id")
    op.drop_column("students", "emis_number")
    op.drop_column("students", "apaar_id")
    op.drop_column("students", "aadhar_number")

    op.drop_column("students", "guardian_aadhar_number")
    op.drop_column("students", "guardian_occupation")
    op.drop_column("students", "guardian_address")
    op.drop_column("students", "mother_annual_income")
    op.drop_column("students", "mother_occupation")
    op.drop_column("students", "mother_email")
    op.drop_column("students", "mother_phone")
    op.drop_column("students", "mother_name")
    op.drop_column("students", "father_annual_income")
    op.drop_column("students", "father_occupation")
    op.drop_column("students", "father_email")
    op.drop_column("students", "father_phone")
    op.drop_column("students", "father_name")

    op.drop_column("students", "identification_marks")
    op.drop_column("students", "disability_details")
    op.drop_column("students", "medical_conditions")
    op.drop_column("students", "medical_allergies")
    op.drop_column("students", "weight_kg")
    op.drop_column("students", "height_cm")
    op.drop_column("students", "blood_group")

