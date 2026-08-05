"""People domain — the humans a school knows.

One Person per human (ADR-001). Business relationships reference that Person;
they never copy identity into themselves. Family participation is expressed as a
relationship value rather than as columns, so a household shape the platform has
never seen still fits (ADR-002).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from core.database import db
from core.models import TenantBaseModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# Family relationships are data, not schema (ADR-002): this list can grow
# without a migration, so no database constraint pins it down.
FAMILY_ROLE_FATHER = "father"
FAMILY_ROLE_MOTHER = "mother"
FAMILY_ROLE_GUARDIAN = "guardian"
FAMILY_ROLE_CHILD = "child"
FAMILY_ROLE_GRANDFATHER = "grandfather"
FAMILY_ROLE_GRANDMOTHER = "grandmother"
FAMILY_ROLE_BROTHER = "brother"
FAMILY_ROLE_SISTER = "sister"
FAMILY_ROLE_UNCLE = "uncle"
FAMILY_ROLE_AUNT = "aunt"
FAMILY_ROLE_RELATIVE = "relative"
FAMILY_ROLE_FOSTER_PARENT = "foster_parent"
FAMILY_ROLE_COURT_APPOINTED_GUARDIAN = "court_appointed_guardian"

KNOWN_FAMILY_ROLES = frozenset(
    {
        FAMILY_ROLE_FATHER,
        FAMILY_ROLE_MOTHER,
        FAMILY_ROLE_GUARDIAN,
        FAMILY_ROLE_CHILD,
        FAMILY_ROLE_GRANDFATHER,
        FAMILY_ROLE_GRANDMOTHER,
        FAMILY_ROLE_BROTHER,
        FAMILY_ROLE_SISTER,
        FAMILY_ROLE_UNCLE,
        FAMILY_ROLE_AUNT,
        FAMILY_ROLE_RELATIVE,
        FAMILY_ROLE_FOSTER_PARENT,
        FAMILY_ROLE_COURT_APPOINTED_GUARDIAN,
    }
)

# Roles that may be compared when deciding whether two records describe the same
# human (ADR-010). Comparing only within a role is what makes it impossible to
# merge a father into a mother who shares the household phone.
#
# Children are excluded, and that exclusion is load-bearing: siblings share a
# household phone and a surname, so comparing them would merge two students into
# one human. An adult recorded once per child is a duplicate; two children are
# two people.
MERGEABLE_FAMILY_ROLES = frozenset(KNOWN_FAMILY_ROLES - {FAMILY_ROLE_CHILD})


class Person(TenantBaseModel):
    """A real human known to the organization.

    Owns everything that belongs to the human rather than to a role they play:
    name, contact details, address, government identification. A Person exists
    whether or not they can sign in (ADR-003).
    """

    __tablename__ = "persons"

    id = db.Column(db.String(36), primary_key=True, default=_new_id)

    full_name = db.Column(db.Text, nullable=False)
    date_of_birth = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(20), nullable=True)

    phone_number = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    address = db.Column(db.Text, nullable=True)
    occupation = db.Column(db.Text, nullable=True)

    aadhaar_number = db.Column(db.String(20), nullable=True)
    photo_url = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Both support duplicate detection, which looks people up by contact
        # detail within one organization.
        db.Index("idx_persons_tenant_id_phone_number", "tenant_id", "phone_number"),
        db.Index("idx_persons_tenant_id_email", "tenant_id", "email"),
    )

    def __repr__(self) -> str:
        return f"<Person {self.id} {self.full_name}>"


class PersonMerge(TenantBaseModel):
    """A record that two Person records were found to be one human.

    ADR-010 promises merges are recoverable. That promise is only real if what
    was combined is written down, so the absorbed person is kept here in full
    rather than being deleted.
    """

    __tablename__ = "person_merges"

    id = db.Column(db.String(36), primary_key=True, default=_new_id)

    kept_person_id = db.Column(
        db.String(36),
        db.ForeignKey("persons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    absorbed_person_id = db.Column(
        db.String(36),
        db.ForeignKey("persons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Everything the absorbed person held at the moment of the merge.
    absorbed_person_details = db.Column(db.JSON, nullable=False)

    # Why they were judged the same human — an automatic rule or a person's name.
    reason = db.Column(db.Text, nullable=True)
    merged_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    def __repr__(self) -> str:
        return f"<PersonMerge {self.absorbed_person_id} into {self.kept_person_id}>"


class Family(TenantBaseModel):
    """The household a school deals with for one or more students."""

    __tablename__ = "families"

    id = db.Column(db.String(36), primary_key=True, default=_new_id)

    # Optional: schools refer to "the Patel family", but a household with two
    # surnames has no natural name and should not be forced into one.
    name = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    def __repr__(self) -> str:
        return f"<Family {self.id} {self.name or 'unnamed'}>"


class FamilyMember(TenantBaseModel):
    """How one Person participates in one Family.

    The relationship is a value rather than a column per role, so single
    parents, grandparents acting as guardians and court-appointed guardians all
    use the same structure (ADR-002).
    """

    __tablename__ = "family_members"

    id = db.Column(db.String(36), primary_key=True, default=_new_id)

    family_id = db.Column(
        db.String(36),
        db.ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_id = db.Column(
        db.String(36),
        db.ForeignKey("persons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship = db.Column(db.String(50), nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    __table_args__ = (
        # One human holds one relationship to one family. A person who is both
        # guardian and grandmother is recorded by the relationship that governs.
        db.UniqueConstraint("family_id", "person_id", name="uq_family_members_family_person"),
    )

    def __repr__(self) -> str:
        return f"<FamilyMember {self.person_id} {self.relationship} of {self.family_id}>"
