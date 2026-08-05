"""every account belongs to a person

The constrain step of ADR-010 for accounts: `users.person_id` becomes mandatory.

The Person each account implies is created here rather than demanded of the
operator. A migration chain has to be runnable end to end against any database
sitting at the previous revision — a step that stops and asks for a script to
be run out of band is a chain no fresh environment can complete, and the break
stays invisible until someone tries.

Only what the account itself knows is copied. A student's date of birth or a
teacher's address is filled in by whoever owns that information; inventing it
here would put facts on a person's record that nobody told us.

Revision ID: 082_account_requires_person
Revises: 081_teacher_academic_participation
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa

revision = "082_account_requires_person"
down_revision = "081_teacher_academic_participation"
branch_labels = None
depends_on = None


# The person id is derived from the account id rather than generated, so
# running this again cannot produce a second person for the same account.
_PERSON_FOR_EVERY_ACCOUNT = sa.text(
    """
    INSERT INTO persons (id, tenant_id, full_name, email, photo_url,
                         created_at, updated_at)
    SELECT md5('person:' || u.id)::uuid::text,
           u.tenant_id,
           -- A person must have a name. An account carrying none gives up the
           -- part of its email before the @, which is what a school will
           -- recognise on the screen.
           COALESCE(
               NULLIF(btrim(u.name), ''),
               NULLIF(split_part(COALESCE(u.email, ''), '@', 1), ''),
               'Unnamed'
           ),
           u.email,
           u.profile_picture_url,
           now(), now()
      FROM users u
     WHERE u.person_id IS NULL
    ON CONFLICT (id) DO NOTHING
    """
)

_LINK_ACCOUNTS_TO_THEIR_PEOPLE = sa.text(
    """
    UPDATE users SET person_id = md5('person:' || id)::uuid::text
     WHERE person_id IS NULL
    """
)


def upgrade():
    bind = op.get_bind()

    bind.execute(_PERSON_FOR_EVERY_ACCOUNT)
    bind.execute(_LINK_ACCOUNTS_TO_THEIR_PEOPLE)

    # Say so rather than assume it: anything still unlinked would otherwise
    # fail below as a null-value stack trace that explains nothing.
    unlinked = bind.execute(
        sa.text("SELECT count(*) FROM users WHERE person_id IS NULL")
    ).scalar()
    if unlinked:
        raise RuntimeError(
            f"{unlinked} account(s) still have no person after the backfill. "
            "Those rows are malformed — check their tenant and email."
        )

    op.alter_column(
        "users", "person_id", existing_type=sa.String(length=36), nullable=False
    )


def downgrade():
    op.alter_column(
        "users", "person_id", existing_type=sa.String(length=36), nullable=True
    )
