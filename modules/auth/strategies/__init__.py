"""Authentication strategies: one class per way of proving an account."""

from .base import AccountMatch, AuthenticationStrategy
from .email_password import EmailPasswordStrategy
from .identifier_password import IdentifierPasswordStrategy
from .mobile_otp import MobileOtpStrategy
from .mobile_pin import MobilePinStrategy
from .registry import (
    DEFAULT_METHOD_KEY,
    AuthenticationStrategyRegistry,
    RegistryInvalid,
    UnknownAuthenticationMethod,
    registry,
)

__all__ = [
    "AccountMatch",
    "AuthenticationStrategy",
    "AuthenticationStrategyRegistry",
    "DEFAULT_METHOD_KEY",
    "EmailPasswordStrategy",
    "IdentifierPasswordStrategy",
    "MobileOtpStrategy",
    "MobilePinStrategy",
    "RegistryInvalid",
    "UnknownAuthenticationMethod",
    "registry",
]
