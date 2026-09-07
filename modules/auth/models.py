"""
Authentication Models

Database models for user authentication and session management.
"""

from core.database import db
from core.models import TenantBaseModel
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import secrets
import uuid
from core.school_time import utc_now


class User(TenantBaseModel):
    """
    User Model
    
    Represents a user in the system. Users can have multiple roles
    and authenticate using email/password. Scoped by tenant.
    """
    __tablename__ = "users"
    __table_args__ = (
        db.UniqueConstraint("email", "tenant_id", name="uq_users_email_tenant"),
        # A person signs in here as one account, or not at all.
        #
        # Partial on `deleted_at IS NULL` deliberately, and not for symmetry
        # with the constraint above — that one ignores soft deletes, which is
        # why every account-creating path has to pass `include_deleted=True`
        # to its duplicate guard or take an IntegrityError. Here a closed
        # account must not stand between a person and a new one, so only live
        # rows are compared.
        #
        # Scoped to the tenant: the same human known to two schools is two
        # Person rows and two accounts (`persons` is tenant-scoped), which is
        # what a tenant membership means. This says nothing about email —
        # two different people may share an address.
        db.Index(
            "uq_users_tenant_person_live",
            "tenant_id",
            "person_id",
            unique=True,
            postgresql_where=db.text("deleted_at IS NULL"),
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Authentication
    # The human this account belongs to (ADR-003). Nullable until the People
    # backfill has run everywhere; a later migration makes it mandatory.
    person_id = db.Column(
        db.String(36),
        db.ForeignKey("persons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Declared as a relationship, not just a column: it is what tells the unit
    # of work to insert the person before the account that references them.
    # Declared from this side so People can see that a person signs in here
    # without importing Identity (ADR-001, and the dependency order).
    person = db.relationship(
        "Person",
        foreign_keys=[person_id],
        backref=db.backref("accounts", lazy=True),
    )

    email = db.Column(db.String(120), nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Profile
    name = db.Column(db.String(120), nullable=True)
    profile_picture_url = db.Column(db.String(255), nullable=True)

    # Email Verification
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    verification_token = db.Column(db.String(255), nullable=True)

    # Password Reset
    reset_password_token = db.Column(db.String(255), nullable=True)
    reset_password_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    force_password_reset = db.Column(db.Boolean, default=False, nullable=False)

    # Platform Admin (Super Admin panel access)
    is_platform_admin = db.Column(db.Boolean, nullable=False, default=False)

    # Login lockout (tenant logins only; platform admin is not locked)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    login_locked_until = db.Column(db.DateTime(timezone=True), nullable=True)

    # Account status
    is_suspended = db.Column(db.Boolean, nullable=False, default=False)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Metadata
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)
    default_unit_id = db.Column(
        db.String(36),
        db.ForeignKey("school_units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Preferred campus for this admin. NULL = show all units. UI filter only, not a permission gate.",
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now
    )

    # Relationships
    sessions = db.relationship(
        "Session",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan"
    )

    # Authority is held by the person's employment, not the account (ADR-013):
    # see modules/rbac/authority_service.py.

    def set_password(self, password: str) -> None:
        """Hash and set user password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify password against stored hash"""
        return check_password_hash(self.password_hash, password)
    
    @classmethod
    def get_user_by_email(cls, email: str, tenant_id: str = None, include_deleted: bool = False):
        """Get user by email address (and tenant_id when provided).

        By default, soft-deleted users (deleted_at IS NOT NULL) are excluded so
        they cannot log in, reset their password, or verify their email.

        Pass include_deleted=True for existence/duplicate guards before creating
        a user: the (email, tenant_id) unique constraint is NOT scoped to
        deleted_at, so a duplicate check must see soft-deleted rows to avoid an
        IntegrityError (HTTP 500) on insert. Our design treats a soft-deleted
        email as non-reusable (the admin restores the account instead).
        """
        q = cls.query.filter_by(email=email)
        if not include_deleted:
            q = q.filter(cls.deleted_at.is_(None))
        if tenant_id is not None:
            q = q.filter_by(tenant_id=tenant_id)
        return q.first()
    
    def generate_email_verification_token(self) -> str:
        """Generate a unique token for email verification"""
        token = str(uuid.uuid4())
        self.verification_token = token
        return token

    def get_email_verification_token(self, email, tenant_id=None) -> str:
        """Get verification token for a user by email (and tenant when provided)."""
        user = User.get_user_by_email(email, tenant_id=tenant_id)
        if user:
            return user.verification_token
        return None

    RESET_TOKEN_EXP_MINUTES = int(os.getenv("RESET_TOKEN_EXP_MINUTES", 30))
    
    def generate_reset_password_token(self):
        """Generate a secure token for password reset"""
        token = secrets.token_urlsafe(32)
        self.reset_password_token = token
        self.reset_password_sent_at = utc_now()
        return token
    
    def is_reset_token_valid(self, token):
        """Check if password reset token is valid and not expired"""
        if not self.reset_password_token:
            return False
        if self.reset_password_token != token:
            return False
        if self.reset_password_sent_at + timedelta(minutes=self.RESET_TOKEN_EXP_MINUTES) < utc_now():
            return False
        return True
    
    def save(self) -> None:
        """Save user to database"""
        db.session.add(self)
        db.session.commit()

    def __repr__(self):
        return f"<User {self.email}>"


REFRESH_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES_DAYS", 7))

def refresh_token_expiry():
    """Calculate refresh token expiry timestamp"""
    return utc_now() + timedelta(days=REFRESH_DAYS)


class Session(TenantBaseModel):
    """
    Session Model
    
    Represents a user session with refresh token.
    Supports multiple concurrent sessions per user. Scoped by tenant.
    """
    __tablename__ = "sessions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )

    refresh_token = db.Column(db.Text, nullable=True, index=True)
    refresh_token_expires_at = db.Column(
        db.DateTime(timezone=True), 
        default=refresh_token_expiry,
        nullable=False
    )

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    last_accessed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    revoked = db.Column(db.Boolean, nullable=False, default=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Device metadata
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4 + IPv6 safe
    user_agent = db.Column(db.String(255), nullable=True)
    device_info = db.Column(db.String(255), nullable=True)
    #: Which authentication method opened this session — the strategy key,
    #: written by the pipeline. Widened from String(20) because
    #: `admission_id_password` is 21 characters and would have truncated.
    #: Rows created before the pipeline keep the column default `"email"`;
    #: they are history, not something to rewrite.
    login_method = db.Column(
        db.String(40),
        nullable=False,
        default="email"
    )

    #: Which client application signed in. Self-declared by the caller, so it
    #: is telemetry and product policy — never a security boundary. Absent
    #: means `unknown`, which is always acceptable: a mobile build that
    #: predates the header must keep working.
    client_surface = db.Column(
        db.String(30),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )

    #: *Which* identifier authenticated, not merely which type. The question
    #: support actually asks is "which address did he sign in with", and a
    #: type cannot answer it.
    authenticated_identifier_id = db.Column(
        db.String(36),
        db.ForeignKey("account_identifiers.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: The refresh token this session was just issued, in memory only.
    #:
    #: Set by `create_session` and by a rotation, read once by whatever builds
    #: the response, and never written to a column — `refresh_tokens` holds
    #: only a digest. An attribute rather than a column so that there is no
    #: place for it to be persisted by accident.
    issued_refresh_token = None

    def revoke(self):
        """Revoke this session, and with it the ability to refresh it.

        Retiring the token generations is part of revoking, not a separate
        step a caller might forget: a session whose token still worked would
        be revoked in name only.
        """
        from .tokens import revoke_session_tokens

        self.revoked = True
        self.revoked_at = utc_now()
        revoke_session_tokens(self.id)
        self.save()
    
    def save(self):
        """Save session to database"""
        db.session.add(self)
        db.session.commit()

    def __repr__(self):
        return f"<Session user_id={self.user_id} revoked={self.revoked}>"


# ---------------------------------------------------------------------------
# How an account is named, and how it is proved
# ---------------------------------------------------------------------------
#
# `users` answers both questions today: the account is found by `email` and
# proved by `password_hash`, and both columns are NOT NULL. That is why a
# student with no email address has no account at all, and why there is no
# place to put a second way of signing in.
#
# The two tables below separate the questions. They are storage only in this
# phase: nothing reads them, login is untouched, and the legacy columns remain
# authoritative. Phase 0d is where authentication starts resolving through
# them.


class AccountIdentifier(TenantBaseModel):
    """A string a human presents to say which account they mean.

    Not a secret. An admission number is printed on a fee receipt and an email
    address is on a website; what proves the account is an AccountCredential.

    Two values are kept — see `modules/auth/identifiers.py`. The raw one is
    what a school's office recognises; the normalized one is what the
    uniqueness index compares, so one address cannot become two accounts by
    being typed with a capital letter.
    """

    __tablename__ = "account_identifiers"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    account_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    identifier_type = db.Column(db.String(30), nullable=False)
    #: As entered, for display and for support to recognise.
    identifier_value = db.Column(db.Text, nullable=False)
    #: The comparison key. Every uniqueness and lookup question uses this.
    identifier_value_normalized = db.Column(db.Text, nullable=False)

    #: Whether NexSchool has evidence the human controls this identifier. An
    #: email is verified by the existing verification flow; an admission
    #: number is verified by the school having issued it.
    is_verified = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.text("false")
    )
    verified_at = db.Column(db.DateTime(timezone=True), nullable=True)

    #: Which of this account's identifiers of this type to show, and to use as
    #: a notification target. At most one per (account, type).
    is_primary = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.text("false")
    )

    issued_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    #: Retiring an identifier keeps the history — support can still answer
    #: "he used to sign in as that" — and frees the value for reissue.
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    account = db.relationship(
        "User",
        foreign_keys=[account_id],
        backref=db.backref(
            "identifiers",
            lazy=True,
            # Both halves, and both are needed. `passive_deletes` stops the ORM
            # loading these rows to blank a NOT NULL column the database is
            # about to cascade away; the cascade covers the case where they are
            # already in the session. `Session` above takes the same shape.
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
    )

    __table_args__ = (
        db.CheckConstraint(
            "identifier_type IN ('email', 'admission_id', 'mobile', 'employee_code')",
            name="ck_account_identifiers_type",
        ),
        # The uniqueness scope: per tenant, per type, live rows only.
        #
        # Partial, unlike `uq_users_email_tenant` — a retired identifier must
        # not stand between the school and reissuing that value, which is the
        # trap the email constraint sets and the reason every account-creating
        # path carries an `include_deleted=True` workaround.
        #
        # Tenant-scoped, and that is load-bearing: an admission number is
        # unique only inside one school, and a household phone number will
        # legitimately appear in two.
        db.Index(
            "uq_account_identifiers_live",
            "tenant_id",
            "identifier_type",
            "identifier_value_normalized",
            unique=True,
            postgresql_where=db.text("deleted_at IS NULL"),
        ),
        # The query sign-in will run. Leads on tenant_id because no lookup is
        # ever legitimately cross-tenant except email, which resolves by a
        # different path.
        db.Index(
            "idx_account_identifiers_lookup",
            "tenant_id",
            "identifier_type",
            "identifier_value_normalized",
        ),
        # "What can this account sign in as?" — the credential admin screens.
        db.Index(
            "idx_account_identifiers_account",
            "account_id",
            "identifier_type",
        ),
        db.Index(
            "uq_account_identifiers_primary",
            "account_id",
            "identifier_type",
            unique=True,
            postgresql_where=db.text("is_primary AND deleted_at IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<AccountIdentifier {self.identifier_type}="
            f"{self.identifier_value_normalized} account={self.account_id}>"
        )


class AccountCredential(TenantBaseModel):
    """A stored secret that proves an account.

    A credential is not an identifier and not a factor. An OTP is a factor —
    issued, verified and destroyed in flight — and gets no row here.

    One live credential of each type per account. A person may hold a password
    and a PIN at once: those are different credentials satisfying different
    authentication methods, not two copies of one secret.
    """

    __tablename__ = "account_credentials"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    account_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    credential_type = db.Column(db.String(20), nullable=False)
    #: Never the secret. Hashed by the same helper `User.set_password` uses.
    secret_hash = db.Column(db.Text, nullable=False)
    #: What produced `secret_hash`, so verification can dispatch on it and a
    #: stronger algorithm can be adopted later by re-hashing on successful
    #: sign-in — which needs no migration precisely because this is recorded
    #: from the first row.
    hash_algorithm = db.Column(db.String(40), nullable=False)

    #: The enforcement flag: the holder must replace this before doing
    #: anything else. Successor to `users.force_password_reset`, which stays
    #: authoritative until a later phase.
    must_change = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.text("false")
    )
    #: The provenance fact: somebody other than the holder chose this secret.
    #: Separate from `must_change` because a school may switch the forced
    #: change off while this stays true — and "still using the password the
    #: school issued" is exactly what a security review asks to see.
    is_provisional = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.text("false")
    )

    issued_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    issued_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    last_rotated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    #: Used for provisional credentials only; null for one the holder chose.
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    #: Retiring a credential keeps the record that it existed and who issued it.
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    account = db.relationship(
        "User",
        foreign_keys=[account_id],
        backref=db.backref(
            "credentials",
            lazy=True,
            # Both halves, and both are needed. `passive_deletes` stops the ORM
            # loading these rows to blank a NOT NULL column the database is
            # about to cascade away; the cascade covers the case where they are
            # already in the session. `Session` above takes the same shape.
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
    )

    __table_args__ = (
        db.CheckConstraint(
            "credential_type IN ('password', 'pin')",
            name="ck_account_credentials_type",
        ),
        db.Index(
            "uq_account_credentials_live",
            "account_id",
            "credential_type",
            unique=True,
            postgresql_where=db.text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self):
        return (
            f"<AccountCredential {self.credential_type} account={self.account_id}>"
        )


# The tenant's authentication policy lives beside the account it governs, in
# its own module so this one stays about what an account *is*. Imported here
# so that importing `modules.auth.models` registers every identity mapper —
# `tests/_model_loader` and `core/database.py` both reach the policy tables
# through this line.
from .policy_models import (  # noqa: E402,F401
    TenantAuthPolicy,
    TenantAuthPolicyRule,
)
from .event_models import AuthEvent  # noqa: E402,F401
