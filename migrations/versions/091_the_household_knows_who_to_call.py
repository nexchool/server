"""A household records the adult the school should call

v1 asked every admission form for a "guardian" — name, relationship and phone,
all required. That is why the field is filled for almost every student and why,
in practice, it usually holds the father: the form demanded a guardian and the
father was who the school had.

Being the contact is not the same fact as being the father. Recording them
separately is what lets the household hold both parents *and* say which one to
ring, instead of storing the father twice under two headings.

The flag is set from what v1 already recorded: whoever the guardian columns
named becomes the contact. That makes the household an exact inverse of the old
field rather than an approximation of it — the reason the family read could not
move before now.

Revision ID: 091_the_household_knows_who_to_call
Revises: 090_identity_and_employment_leave_their_records
"""
from alembic import op
import sqlalchemy as sa


revision = "091_the_household_knows_who_to_call"
down_revision = "090_identity_and_employment_leave_their_records"
branch_labels = None
depends_on = None


# Whoever the guardian columns named. Matched on name, because that is what the
# family backfill used to create them and it is all the two records share.
_CONTACT_FROM_THE_GUARDIAN_COLUMNS = sa.text(
    """
    UPDATE family_members SET is_primary_contact = true
     WHERE id IN (
        -- DISTINCT ON: two siblings can name different guardians, and a
        -- household has one person the school calls.
        SELECT DISTINCT ON (fm.family_id) fm.id
          FROM family_members fm
          JOIN persons p ON p.id = fm.person_id
          JOIN family_members child
            ON child.family_id = fm.family_id AND child.relationship = 'child'
          JOIN students st ON st.person_id = child.person_id
         WHERE fm.relationship <> 'child'
           AND st.guardian_name IS NOT NULL
           AND btrim(lower(p.full_name)) = btrim(lower(st.guardian_name))
         ORDER BY fm.family_id, fm.created_at
     )
    """
)

# A household whose guardian was never recorded, or whose name no longer
# matches anyone in it, still needs someone to call. The father is who a school
# names first, then the mother, then whoever else is there.
_CONTACT_WHERE_NOBODY_WAS_CHOSEN = sa.text(
    """
    UPDATE family_members fm SET is_primary_contact = true
     WHERE fm.id IN (
        SELECT DISTINCT ON (candidate.family_id) candidate.id
          FROM family_members candidate
         WHERE candidate.relationship <> 'child'
           AND NOT EXISTS (
                 SELECT 1 FROM family_members held
                  WHERE held.family_id = candidate.family_id
                    AND held.is_primary_contact
               )
         ORDER BY candidate.family_id,
                  CASE candidate.relationship
                       WHEN 'father' THEN 1
                       WHEN 'mother' THEN 2
                       ELSE 3 END,
                  candidate.created_at
     )
    """
)


def upgrade():
    op.add_column(
        "family_members",
        sa.Column(
            "is_primary_contact",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    bind = op.get_bind()
    bind.execute(_CONTACT_FROM_THE_GUARDIAN_COLUMNS)
    bind.execute(_CONTACT_WHERE_NOBODY_WAS_CHOSEN)

    op.create_index(
        "uq_family_members_primary_contact",
        "family_members",
        ["family_id"],
        unique=True,
        postgresql_where=sa.text("is_primary_contact"),
    )


def downgrade():
    op.drop_index("uq_family_members_primary_contact", table_name="family_members")
    op.drop_column("family_members", "is_primary_contact")
