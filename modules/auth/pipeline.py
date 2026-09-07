"""One way in, and one place where the gates are.

Before this, sign-in was a route function with two branches chosen by the
request body, each carrying its own copy of the checks. That shape has already
failed once here: the two branches disagreed about counting failed attempts,
so omitting `tenant_id` from the body bought unlimited guesses against any
account. `record_failed_login` was made the single owner of that rule as a
result, and this module is the same argument applied to every other gate.

    A strategy answers two questions — which accounts could this identifier
    mean, and is this proof valid. Everything else happens here, once, in a
    fixed order, for every method that will ever exist.

The order is the security contract, not an implementation detail:

     1. parse and validate the request
     2. select the strategy                       (unknown method -> refuse)
     3. resolve the tenant                        (existing resolver)
     4. GATE  tenant active / maintenance mode
     5. resolve candidate accounts                (strategy.resolve)
     6. GATE  tenant authentication policy
     7. GATE  lockout
     8. verify the proof                          (strategy.verify)
     9. GATE  account status / identifier verification
    10. disambiguate                              (which school?)
    11. record the authentication event
    12. finalize                                  (the existing _finalize_login)

Two of those placements are load-bearing and easy to get wrong:

* **Policy is evaluated before the proof.** A denied method must not consume
  a verification — and, once a method costs money to attempt, must not spend
  it either.
* **Permissions are checked last, inside the existing finalization.** That
  ordering is what stops `NoPermissions` becoming a way to discover whether an
  account exists: it is reachable only after a correct password.

What this module deliberately does not do is change what any of those gates
decide. Phase 0d moves them; it does not rule differently.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from flask import g

from core.database import db
from core.school_time import utc_now

from .event_models import (
    EVENT_LOGIN_FAILURE,
    EVENT_LOGIN_SUCCESS,
    REASON_ACCOUNT_LOCKED,
    REASON_CREDENTIAL_MISMATCH,
    REASON_MAINTENANCE_MODE,
    REASON_MISSING_CREDENTIALS,
    REASON_NO_IDENTIFIER_MATCH,
    REASON_POLICY_DENIED,
    REASON_THROTTLED,
    REASON_TENANT_CHOICE_REQUIRED,
    REASON_TENANT_UNRESOLVED,
    REASON_UNKNOWN_METHOD,
    AuthEvent,
    hash_identifier,
)
from .strategies import DEFAULT_METHOD_KEY, UnknownAuthenticationMethod, registry
from .strategies.base import ThrottledOut

logger = logging.getLogger(__name__)

#: What a caller that declares no client application is recorded as. Always
#: acceptable — a build that predates the header must keep working.
SURFACE_UNKNOWN = "unknown"

#: Where the pipeline leaves what it learned, for `create_session` and
#: `generate_access_token` to pick up without `_finalize_login` — which this
#: phase must not modify — having to pass it through.
AUTH_CONTEXT = "_auth_context"


@dataclass
class AuthenticationRequest:
    """A sign-in attempt, free of Flask.

    Built once at the edge so strategies and gates never reach for the request
    object, and so a test can drive the pipeline without one.
    """

    identifier: str
    proof: str
    method_key: str = DEFAULT_METHOD_KEY
    tenant_id: Optional[str] = None
    subdomain: Optional[str] = None
    client_surface: str = SURFACE_UNKNOWN
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    #: The body as received, for the existing tenant resolver, which reads
    #: `tenant_id` / `tenantId` / `subdomain` itself.
    raw_body: Dict[str, Any] = field(default_factory=dict)

    @property
    def names_a_tenant(self) -> bool:
        """Whether the *body* named a school.

        Deliberately the body and not the headers: that is what today's login
        uses to choose between its two branches, and Phase 0d preserves the
        behaviour rather than improving it.
        """
        return bool(self.tenant_id or self.subdomain)

    @classmethod
    def from_flask(cls, request) -> "AuthenticationRequest":
        data = request.get_json(silent=True) or {}
        return cls(
            identifier=(data.get("email") or data.get("identifier") or "").strip(),
            proof=data.get("password") or "",
            # An absent method is email and password. Old clients send none.
            method_key=(data.get("method") or DEFAULT_METHOD_KEY).strip(),
            tenant_id=data.get("tenant_id") or data.get("tenantId"),
            subdomain=(data.get("subdomain") or "").strip() or None,
            client_surface=(
                request.headers.get("X-Client-Surface") or SURFACE_UNKNOWN
            ).strip()[:30]
            or SURFACE_UNKNOWN,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
            raw_body=data,
        )


@dataclass
class AuthenticationOutcome:
    """What the pipeline decided. The route turns it into HTTP."""

    #: Ready to finalize.
    account: object = None
    tenant: object = None
    identifier: object = None
    method_key: str = DEFAULT_METHOD_KEY
    client_surface: str = SURFACE_UNKNOWN
    #: More than one school matched; the caller must choose.
    tenant_choices: Optional[List[object]] = None
    #: Refused. `error` is what the client is told; `reason` is what is
    #: recorded. They are different on purpose.
    error: Optional[str] = None
    message: Optional[str] = None
    status_code: int = 401
    reason: Optional[str] = None
    #: The operator entering a school rather than a member of it. Carried
    #: through to the existing finalization, which audits it.
    is_god_login: bool = False

    @property
    def succeeded(self) -> bool:
        return self.account is not None and self.error is None

    @property
    def needs_tenant_choice(self) -> bool:
        return bool(self.tenant_choices)


class AuthenticationService:
    """Executes one sign-in attempt."""

    def __init__(self, strategy_registry=registry):
        self._registry = strategy_registry

    # -- the pipeline --------------------------------------------------------

    def authenticate(self, request: AuthenticationRequest) -> AuthenticationOutcome:
        started = time.monotonic()
        outcome = self._run(request)
        self._record(request, outcome, time.monotonic() - started)
        return outcome

    def _run(self, request: AuthenticationRequest) -> AuthenticationOutcome:
        # 1. Parse and validate.
        if not request.identifier or not request.proof:
            return self._refuse(
                request,
                error="ValidationError",
                message="Email and password are required",
                status_code=400,
                reason=REASON_MISSING_CREDENTIALS,
            )

        # 2. Select the strategy. An unknown method is refused, never
        #    downgraded to email and password.
        try:
            strategy = self._registry.get(request.method_key)
        except UnknownAuthenticationMethod:
            return self._refuse(
                request,
                error="UnsupportedAuthenticationMethod",
                message="That sign-in method is not available.",
                status_code=400,
                reason=REASON_UNKNOWN_METHOD,
            )

        # 3. Resolve the tenant, through the existing resolver — unchanged,
        #    including its fallback to the configured default, which is a
        #    documented behaviour this phase deliberately does not alter.
        tenant = None
        if request.names_a_tenant:
            from core.tenant import resolve_tenant_for_auth

            failure = resolve_tenant_for_auth(request.raw_body)
            if failure:
                return self._refuse(
                    request,
                    error="TenantRequired",
                    message="Tenant is required.",
                    status_code=failure[0],
                    reason=REASON_TENANT_UNRESOLVED,
                    response=failure,
                )
            tenant = self._resolved_tenant()
        elif strategy.requires_tenant:
            # Only email may be resolved without a school. Every other
            # identifier is unique per tenant at best.
            return self._refuse(
                request,
                error="TenantRequired",
                message="Tenant is required for this sign-in method.",
                status_code=400,
                reason=REASON_TENANT_UNRESOLVED,
            )

        tenant_id = tenant.id if tenant is not None else None

        # 4. GATE — maintenance mode.
        if self._in_maintenance():
            return self._refuse(
                request,
                error="MaintenanceMode",
                message="Logins are temporarily disabled. Please try again later.",
                status_code=503,
                reason=REASON_MAINTENANCE_MODE,
                tenant=tenant,
            )

        # 5. Candidate accounts.
        matches = strategy.resolve(request.identifier, tenant_id)
        if not matches:
            # Usually how a god-login arrives: the operator has no account in
            # the school they are entering.
            god = self._god_login(request, tenant)
            if god is not None:
                return god

            # Nothing to count against, and nothing to say — the response is
            # the same one a wrong password gets.
            self._count_failures_for_identifier(request, strategy, tenant_id)
            return self._refuse(
                request,
                error="InvalidCredentials",
                message="Invalid email or password",
                reason=REASON_NO_IDENTIFIER_MATCH,
                tenant=tenant,
            )

        # 6. GATE — policy. Before the proof, so a denied method never
        #    consumes a verification.
        permitted = [
            match
            for match in matches
            if self._policy_permits(match.account, strategy.key, request.client_surface)
        ]
        if not permitted:
            # Externally identical to a wrong password, and that is the point.
            # A caller who could tell "this account exists but the method is
            # off" from "no such account" would have an account-enumeration
            # oracle needing no password at all — and this gate runs *before*
            # the proof, so it was one. The real reason still reaches the
            # audit record below; only the answer is coarse.
            return self._refuse(
                request,
                error="InvalidCredentials",
                message="Invalid email or password",
                reason=REASON_POLICY_DENIED,
                tenant=tenant,
                account=matches[0].account,
            )

        # 7. GATE — lockout, before any password is checked.
        for match in permitted:
            if self._is_locked(match.account):
                # Also uniform, and for a sharper reason than the policy gate:
                # a distinct 429 told an unauthenticated attacker not only
                # that an account exists but that it is *currently under
                # attack* — which is a live signal about which accounts are
                # worth attacking. The lock still holds; it is just not
                # announced.
                return self._refuse(
                    request,
                    error="InvalidCredentials",
                    message="Invalid email or password",
                    reason=REASON_ACCOUNT_LOCKED,
                    tenant=tenant,
                    account=match.account,
                )

        # 8. Verify.
        # What the method needs from the request beyond the proof. A password
        # strategy ignores it; the OTP strategy uses it to insist that a named
        # challenge is the one being spent.
        context = {"challenge_id": request.raw_body.get("challenge_id")}
        throttled = False
        verified = []
        for match in permitted:
            try:
                if strategy.verify(match, request.proof, context):
                    verified.append(match)
            except ThrottledOut:
                # The method's own limiter declined. Refused, but *not* counted
                # against the account — see `ThrottledOut`. Otherwise knowing
                # somebody's mobile number would be enough to lock them out of
                # every other way in.
                throttled = True

        if throttled and not verified:
            return self._refuse(
                request,
                error="InvalidCredentials",
                message="Invalid email or password",
                reason=REASON_THROTTLED,
                tenant=tenant,
                account=permitted[0].account,
            )
        if not verified:
            # The platform admin's way in, tried only after a real tenant user
            # has failed — the precedence the legacy path has always had, and
            # which this phase must not alter. Only on the branch that named a
            # school: with none named, the admin's own account is found by the
            # ordinary cross-tenant search, exactly as before.
            god = self._god_login(request, tenant)
            if god is not None:
                return god

            self._count_failures(permitted, strategy)
            return self._refuse(
                request,
                error="InvalidCredentials",
                message="Invalid email or password",
                reason=REASON_CREDENTIAL_MISMATCH,
                tenant=tenant,
                account=permitted[0].account,
            )

        # 10. Disambiguate. (9 — account status, verification and permissions —
        #     is enforced inside the existing finalization, which is where it
        #     already lives and which this phase must not modify. Keeping it
        #     there also keeps `NoPermissions` reachable only after a correct
        #     password, so it cannot be used to probe for accounts.)
        if len(verified) > 1:
            return AuthenticationOutcome(
                method_key=strategy.key,
                client_surface=request.client_surface,
                tenant_choices=[match.tenant for match in verified],
                reason=REASON_TENANT_CHOICE_REQUIRED,
            )

        match = verified[0]
        return AuthenticationOutcome(
            account=match.account,
            tenant=match.tenant if tenant is None else tenant,
            identifier=match.identifier,
            method_key=strategy.key,
            client_surface=request.client_surface,
        )

    def _resolved_tenant(self):
        """The school this request is scoped to.

        `g.tenant_id` is the authoritative marker — it is what arms the ORM's
        tenant scoping — and `g.tenant` is a convenience the resolver sets
        alongside it. They can disagree: `resolve_tenant_for_auth` returns
        early when `g.tenant_id` is already set (middleware may have resolved
        it from a header or the Host), and that early return leaves `g.tenant`
        unset.

        Reading only `g.tenant` therefore yielded `tenant_id = None` for a
        request that was perfectly well scoped, which for a tenant-required
        method meant every lookup found nothing — and for email, which treats
        no tenant as "search them all", meant a scoped request quietly became
        a cross-tenant search that happened to return the right account
        because an address is near-unique. So the id is the source of truth
        here, and the object is fetched from it when it is missing.
        """
        tenant = getattr(g, "tenant", None)
        if tenant is not None:
            return tenant

        tenant_id = getattr(g, "tenant_id", None)
        if not tenant_id:
            return None

        from core.models import Tenant

        tenant = db.session.get(Tenant, tenant_id)
        if tenant is not None:
            g.tenant = tenant
        return tenant

    # -- gates ---------------------------------------------------------------

    def _in_maintenance(self) -> bool:
        from modules.platform.services import get_platform_settings

        try:
            return get_platform_settings().get("maintenance_mode") == "true"
        except Exception:
            # A setting that cannot be read must not close the door.
            logger.warning("Could not read maintenance_mode", exc_info=True)
            return False

    def _policy_permits(self, account, method_key: str, surface: str) -> bool:
        """A3 is the policy service's own rule, not a special case here."""
        from .policy import is_method_allowed

        return is_method_allowed(account, method_key, surface)

    def _is_locked(self, account) -> bool:
        if getattr(account, "is_platform_admin", False):
            return False
        locked_until = getattr(account, "login_locked_until", None)
        return bool(locked_until and locked_until > utc_now())

    def _god_login(self, request, tenant) -> Optional[AuthenticationOutcome]:
        """A platform administrator entering a school with their own password.

        Left exactly where the legacy path had it and shaped exactly as it was:
        only when the request named a school, only after a tenant user with
        those credentials has failed, and only for the email-and-password
        method. Not a registered strategy — the operator's authority is the
        platform flag, not a subject kind, and A3 keeps the school's policy out
        of it.
        """
        if tenant is None or request.method_key != DEFAULT_METHOD_KEY:
            return None

        from .services import authenticate_platform_admin

        admin = authenticate_platform_admin(request.identifier, request.proof)
        if admin is None:
            return None

        return AuthenticationOutcome(
            account=admin,
            tenant=tenant,
            identifier=None,
            method_key=request.method_key,
            client_surface=request.client_surface,
            is_god_login=True,
        )

    def _count_failures(self, matches, strategy=None) -> None:
        """One owner for the failed-attempt rule, whichever branch got here.

        A method that brings its own limiter is exempt: see
        `counts_toward_account_lockout` on the strategy base for why a
        semi-public identifier must not be able to spend the account's shared
        budget.
        """
        from .services import max_login_attempts, record_failed_login

        if strategy is not None and not strategy.counts_toward_account_lockout:
            return

        limit = max_login_attempts()
        for match in matches:
            record_failed_login(match.account, max_attempts=limit)

    def _count_failures_for_identifier(self, request, strategy, tenant_id) -> None:
        """Count a guess that matched no account, against every account holding
        that identifier — the rule the tenant-less branch once skipped."""
        if strategy.key != DEFAULT_METHOD_KEY:
            return
        from .services import accounts_for_email, max_login_attempts, record_failed_login

        limit = max_login_attempts()
        for account in accounts_for_email(request.identifier):
            if tenant_id and account.tenant_id != tenant_id:
                continue
            record_failed_login(account, max_attempts=limit)

    # -- refusals and records -------------------------------------------------

    def _refuse(
        self,
        request,
        *,
        error,
        message,
        reason,
        status_code=401,
        tenant=None,
        account=None,
        response=None,
    ) -> AuthenticationOutcome:
        outcome = AuthenticationOutcome(
            method_key=request.method_key,
            client_surface=request.client_surface,
            error=error,
            message=message,
            status_code=status_code,
            reason=reason,
        )
        outcome.tenant = tenant
        outcome.account = None
        # Kept off `account` so `succeeded` stays false; recorded separately so
        # the event can name who was being attempted.
        outcome._attempted_account = account  # noqa: SLF001
        outcome._tenant_response = response  # noqa: SLF001
        return outcome

    def _record(self, request, outcome, elapsed_seconds: float) -> None:
        """One event per attempt, emitted here and nowhere else.

        A strategy does not decide whether an attempt is audited: the pipeline
        is what knows the method, the surface, the school, the candidate and
        the reason.
        """
        account = outcome.account or getattr(outcome, "_attempted_account", None)
        tenant = outcome.tenant
        succeeded = outcome.succeeded

        try:
            db.session.add(
                AuthEvent(
                    tenant_id=getattr(tenant, "id", None)
                    or getattr(account, "tenant_id", None),
                    account_id=getattr(account, "id", None),
                    identifier_type=self._identifier_type_for(request),
                    identifier_value_hash=hash_identifier(request.identifier),
                    method_key=request.method_key,
                    event_type=(
                        EVENT_LOGIN_SUCCESS if succeeded else EVENT_LOGIN_FAILURE
                    ),
                    reason=outcome.reason,
                    client_surface=request.client_surface,
                    ip_address=request.ip_address,
                    user_agent=(request.user_agent or "")[:255] or None,
                )
            )
            db.session.flush()
        except Exception:
            # An attempt must not fail because it could not be recorded.
            logger.exception("Could not record authentication event")

        logger.info(
            "auth.login.%s", "success" if succeeded else "failure",
            extra={
                "metric": f"auth.login.{'success' if succeeded else 'failure'}",
                "auth_method": request.method_key,
                "client_surface": request.client_surface,
                "tenant_id": getattr(tenant, "id", None),
                "reason": outcome.reason,
                "latency_ms": round(elapsed_seconds * 1000, 2),
            },
        )

    def _identifier_type_for(self, request) -> Optional[str]:
        try:
            return self._registry.get(request.method_key).identifier_type
        except UnknownAuthenticationMethod:
            return None


def publish_context(outcome: AuthenticationOutcome) -> None:
    """Leave what the pipeline learned where session and token creation find it.

    `_finalize_login` is explicitly out of scope for this phase, so the
    metadata reaches `create_session` and `generate_access_token` through the
    request context rather than through its signature.
    """
    setattr(
        g,
        AUTH_CONTEXT,
        {
            "login_method": outcome.method_key,
            "client_surface": outcome.client_surface,
            "authenticated_identifier_id": getattr(outcome.identifier, "id", None),
        },
    )


def current_context() -> Dict[str, Any]:
    from flask import has_request_context

    if not has_request_context():
        return {}
    return getattr(g, AUTH_CONTEXT, None) or {}


def clear_context() -> None:
    from flask import has_request_context

    if has_request_context() and hasattr(g, AUTH_CONTEXT):
        delattr(g, AUTH_CONTEXT)


def pipeline_enabled() -> bool:
    """Whether sign-in runs through the pipeline or the legacy implementation.

    The rollback mechanism: flipping the platform setting returns
    authentication to the path it used before this phase, with no deploy.
    Missing means enabled — the pipeline is the intended path, and a setting
    nobody has written must never be able to turn authentication off.
    """
    from modules.platform.services import get_platform_setting

    try:
        configured = get_platform_setting("auth_pipeline_enabled")
    except Exception:
        logger.warning("Could not read auth_pipeline_enabled", exc_info=True)
        return True
    if configured is None:
        return True
    return str(configured).strip().lower() not in ("false", "0", "no", "off")
