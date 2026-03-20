"""
Authentication Models

Database models for user authentication and session management.
"""

from backend.core.database import db
from backend.core.models import TenantBaseModel
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import secrets
import uuid


class User(TenantBaseModel):
    """
    User Model
    
    Represents a user in the system. Users can have multiple roles
    and authenticate using email/password. Scoped by tenant.
    """
    __tablename__ = "users"
    __table_args__ = (
        db.UniqueConstraint("email", "tenant_id", name="uq_users_email_tenant"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Authentication
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
    reset_password_sent_at = db.Column(db.DateTime, nullable=True)
    force_password_reset = db.Column(db.Boolean, default=False, nullable=False)

    # Platform Admin (Super Admin panel access)
    is_platform_admin = db.Column(db.Boolean, nullable=False, default=False)

    # Login lockout (tenant logins only; platform admin is not locked)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    login_locked_until = db.Column(db.DateTime, nullable=True)

    # Metadata
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # Relationships
    sessions = db.relationship(
        "Session",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan"
    )

    # Note: roles relationship is defined in RBAC module via UserRole model

    def set_password(self, password: str) -> None:
        """Hash and set user password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify password against stored hash"""
        return check_password_hash(self.password_hash, password)
    
    @classmethod
    def get_user_by_email(cls, email: str, tenant_id: str = None):
        """Get user by email address (and tenant_id when provided)."""
        q = cls.query.filter_by(email=email)
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
        self.reset_password_sent_at = datetime.utcnow()
        return token
    
    def is_reset_token_valid(self, token):
        """Check if password reset token is valid and not expired"""
        if not self.reset_password_token:
            return False
        if self.reset_password_token != token:
            return False
        if self.reset_password_sent_at + timedelta(minutes=self.RESET_TOKEN_EXP_MINUTES) < datetime.utcnow():
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
    return datetime.utcnow() + timedelta(days=REFRESH_DAYS)


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
        db.DateTime, 
        default=refresh_token_expiry,
        nullable=False
    )

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_accessed_at = db.Column(db.DateTime, nullable=True)

    revoked = db.Column(db.Boolean, nullable=False, default=False)
    revoked_at = db.Column(db.DateTime, nullable=True)

    # Device metadata
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4 + IPv6 safe
    user_agent = db.Column(db.String(255), nullable=True)
    device_info = db.Column(db.String(255), nullable=True)
    login_method = db.Column(
        db.String(20),
        nullable=False,
        default="email"
    )

    def revoke(self):
        """Revoke this session"""
        self.revoked = True
        self.revoked_at = datetime.utcnow()
        self.save()
    
    def save(self):
        """Save session to database"""
        db.session.add(self)
        db.session.commit()

    def __repr__(self):
        return f"<Session user_id={self.user_id} revoked={self.revoked}>"
