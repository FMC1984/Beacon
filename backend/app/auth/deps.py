"""The request principal and the dependencies routers use to enforce it.

Three ways in:
  session     Authorization: Bearer <token>   a signed-in user
  access_key  X-Beacon-Key                    the shared key, kept for scripts
  open        nothing at all                  only while no user exists AND no
                                              access key is configured (a fresh
                                              local checkout, the test suite)

Platform admins see every organization unless X-Beacon-Org names one; everyone
else is pinned to an organization they hold a membership in.
"""

import secrets
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth.service import find_session, memberships_for
from app.config import settings
from app.db import get_db
from app.models import OrgMembership, Property, User
from app.models.user import ROLE_ADMIN, ROLE_NONE, ROLE_OWNER, ROLE_PLATFORM_ADMIN, ROLE_RANK, ROLE_VIEWER

ORG_HEADER = "x-beacon-org"


@dataclass
class Principal:
    user: User | None
    org_id: int | None
    role: str
    is_platform_admin: bool
    via: str
    memberships: list[OrgMembership] = field(default_factory=list)

    def has_role(self, min_role: str) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[min_role]

    def role_in(self, organization_id: int) -> str | None:
        if self.is_platform_admin:
            return ROLE_PLATFORM_ADMIN
        for m in self.memberships:
            if m.organization_id == organization_id:
                return m.role
        return None


def _org_from_header(request: Request) -> int | None:
    raw = request.headers.get(ORG_HEADER)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Beacon-Org must be an organization id.")


def _principal_for_user(user: User, memberships: list[OrgMembership], org_id: int | None) -> Principal:
    if user.is_platform_admin:
        return Principal(user, org_id, ROLE_PLATFORM_ADMIN, True, "session", memberships)
    if org_id is not None:
        for m in memberships:
            if m.organization_id == org_id:
                return Principal(user, org_id, m.role, False, "session", memberships)
        raise HTTPException(status_code=403, detail="You are not a member of that organization.")
    if not memberships:
        # Signed in but in no organization: can see their own account and
        # nothing else (rank 0 fails every role gate; no org means no data).
        return Principal(user, None, ROLE_NONE, False, "session", memberships)
    first = memberships[0]
    return Principal(user, first.organization_id, first.role, False, "session", memberships)


def _resolve_principal(request: Request, db: Session) -> Principal:
    org_id = _org_from_header(request)
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        sess = find_session(db, token) if token else None
        if sess is None:
            raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.")
        user = db.get(User, sess.user_id)
        return _principal_for_user(user, memberships_for(db, user), org_id)
    key = request.headers.get("x-beacon-key", "")
    if settings.access_key and key and secrets.compare_digest(key, settings.access_key):
        return Principal(None, org_id, ROLE_PLATFORM_ADMIN, True, "access_key")
    if not settings.access_key and db.query(User.id).first() is None:
        return Principal(None, org_id, ROLE_PLATFORM_ADMIN, True, "open")
    raise HTTPException(status_code=401, detail="Sign in required.")


async def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    """Async on purpose: it runs on the request task, so the principal it
    stores in the context is visible to the sync handler and every service the
    handler calls (scope filtering in services/metrics.py relies on this)."""
    from app.auth.context import set_current

    principal = _resolve_principal(request, db)
    set_current(principal)
    return principal


def require_role(min_role: str):
    def dep(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has_role(min_role):
            raise HTTPException(status_code=403, detail=f"This needs the {min_role} role.")
        return principal

    return dep


def require_platform_admin(principal: Principal = Depends(current_principal)) -> Principal:
    if not principal.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform admins only.")
    return principal


def require_org_role(principal: Principal, organization_id: int, min_role: str) -> str:
    """The caller's role inside a specific organization, or 403."""
    role = principal.role_in(organization_id)
    if role is None or ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail=f"This needs the {min_role} role in that organization.")
    return role


def role_gate(request: Request, principal: Principal = Depends(current_principal),
              db: Session = Depends(get_db)) -> Principal:
    """Router-level gate: reads need viewer, writes need admin, and writes
    inside an organization with no active subscription (and no override)
    get 402 so the data stays readable but frozen until billing starts."""
    needed = ROLE_VIEWER if request.method in ("GET", "HEAD", "OPTIONS") else ROLE_ADMIN
    if not principal.has_role(needed):
        raise HTTPException(status_code=403, detail=f"This needs the {needed} role.")
    if needed == ROLE_ADMIN and principal.org_id is not None and not principal.is_platform_admin:
        from app.services.billing.entitlement import entitlement

        if not entitlement(db, principal.org_id).active:
            raise HTTPException(
                status_code=402,
                detail={"code": "subscription_required",
                        "message": "Start monitoring to make changes. Everything stays readable meanwhile."},
            )
    return principal


def assert_property_access(db: Session, principal: Principal, property_id: int) -> Property:
    """404 (never 403) so a foreign property's existence does not leak."""
    from app.services.observatory.tenancy import property_org_id

    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    if principal.org_id is None:
        if not principal.is_platform_admin:
            raise HTTPException(status_code=404, detail="Property not found.")
    elif property_org_id(db, property_id) != principal.org_id:
        raise HTTPException(status_code=404, detail="Property not found.")
    return prop


def require_property(property_id: int, principal: Principal = Depends(current_principal),
                     db: Session = Depends(get_db)) -> Property:
    return assert_property_access(db, principal, property_id)


def scope_property(property_id: int | None = Query(default=None), principal: Principal = Depends(current_principal),
                   db: Session = Depends(get_db)) -> Property | None:
    """For routes where property_id is an optional query parameter: checked
    when given, ignored when absent (the portfolio scope is narrowed elsewhere)."""
    if property_id is None:
        return None
    return assert_property_access(db, principal, property_id)


__all__ = [
    "Principal", "current_principal", "require_role", "require_platform_admin", "require_org_role",
    "role_gate", "assert_property_access", "require_property", "ROLE_VIEWER", "ROLE_ADMIN", "ROLE_OWNER",
]
