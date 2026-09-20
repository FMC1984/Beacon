"""Sign in, sessions, invites, password resets and team management."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.deps import Principal, current_principal, require_org_role
from app.auth.passwords import hash_password, password_problem, verify_password
from app.auth.ratelimit import login_limiter, reset_limiter
from app.auth.service import (
    create_invite,
    create_reset,
    create_session,
    create_user,
    find_invite,
    find_open_reset,
    invite_link,
    invite_state,
    memberships_for,
    normalize_email,
    reset_link,
    revoke_all_sessions,
    revoke_session,
    set_membership,
)
from app.db import get_db
from app.models import Invite, Organization, OrgMembership, User
from app.models.user import ORG_ROLES, ROLE_OWNER
from app.schemas.auth import (
    InviteAccept,
    InviteCreate,
    InviteOut,
    InvitePublic,
    LoginIn,
    LoginOut,
    MeOut,
    MemberOut,
    MembersOut,
    MembershipOut,
    OrgOut,
    PasswordChange,
    PendingInviteOut,
    ResetConfirm,
    ResetRequest,
    RoleChange,
    UserOut,
)
from app.services.email import send_email

router = APIRouter(prefix="/auth", tags=["auth"])

PUBLIC_ROUTES = {
    ("POST", "/api/auth/login"),
    ("GET", "/api/auth/invites/{token}"),
    ("POST", "/api/auth/invites/{token}/accept"),
    ("POST", "/api/auth/reset/request"),
    ("GET", "/api/auth/reset/{token}"),
    ("POST", "/api/auth/reset/{token}/confirm"),
}


def _client_key(request: Request, email: str) -> str:
    host = request.client.host if request.client else ""
    return f"{email}|{host}"


def _org_out(org: Organization, role: str) -> OrgOut:
    return OrgOut(id=org.id, name=org.name, slug=org.slug, role=role,
                  sample_data=bool((org.settings or {}).get("sample_data")))


def _me(db: Session, principal: Principal) -> MeOut:
    user_out = None
    memberships: list[MembershipOut] = []
    if principal.user is not None:
        u = principal.user
        user_out = UserOut(id=u.id, email=u.email, name=u.name, is_platform_admin=u.is_platform_admin,
                           last_login_at=u.last_login_at)
        for m in principal.memberships:
            org = db.get(Organization, m.organization_id)
            if org is None:
                continue
            memberships.append(MembershipOut(
                organization_id=org.id, organization_name=org.name, organization_slug=org.slug,
                role=m.role, sample_data=bool((org.settings or {}).get("sample_data")),
            ))
    org_out = None
    if principal.org_id is not None:
        org = db.get(Organization, principal.org_id)
        if org is not None:
            org_out = _org_out(org, principal.role)
    organizations: list[OrgOut] = []
    if principal.is_platform_admin:
        organizations = [_org_out(o, "platform_admin")
                         for o in db.query(Organization).filter_by(is_active=True).order_by(Organization.name).all()]
    else:
        organizations = [OrgOut(id=m.organization_id, name=m.organization_name, slug=m.organization_slug,
                                role=m.role, sample_data=m.sample_data) for m in memberships]
    return MeOut(user=user_out, via=principal.via, is_platform_admin=principal.is_platform_admin,
                 org=org_out, memberships=memberships, organizations=organizations)


def _principal_for_login(db: Session, user: User) -> Principal:
    from app.auth.deps import _principal_for_user

    return _principal_for_user(user, memberships_for(db, user), None)


# --- sign in ----------------------------------------------------------------------


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    key = _client_key(request, email)
    if not login_limiter.allowed(key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
    user = db.query(User).filter_by(email=email).first()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        login_limiter.hit(key)
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    login_limiter.reset(key)
    user.last_login_at = datetime.utcnow()
    db.commit()
    token = create_session(db, user, request.headers.get("user-agent"))
    me = _me(db, _principal_for_login(db, user))
    return LoginOut(token=token, **me.model_dump())


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db),
           principal: Principal = Depends(current_principal)):
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        revoke_session(db, auth[7:].strip())
    return {"status": "signed_out"}


@router.get("/me", response_model=MeOut)
def me(db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    return _me(db, principal)


@router.post("/password")
def change_password(payload: PasswordChange, request: Request, db: Session = Depends(get_db),
                    principal: Principal = Depends(current_principal)):
    if principal.user is None:
        raise HTTPException(status_code=400, detail="Sign in with a user account to change a password.")
    if not verify_password(payload.current_password, principal.user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    problem = password_problem(payload.new_password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    principal.user.password_hash = hash_password(payload.new_password)
    db.commit()
    auth = request.headers.get("authorization", "")
    keep = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    revoked = revoke_all_sessions(db, principal.user.id, keep_token=keep)
    return {"status": "changed", "other_sessions_signed_out": revoked}


# --- invites ----------------------------------------------------------------------


@router.post("/invites", response_model=InviteOut, status_code=201)
def create_invite_route(payload: InviteCreate, db: Session = Depends(get_db),
                        principal: Principal = Depends(current_principal)):
    org = db.get(Organization, payload.organization_id)
    if org is None or not org.is_active:
        raise HTTPException(status_code=404, detail="Organization not found.")
    require_org_role(principal, org.id, ROLE_OWNER)
    if payload.role not in ORG_ROLES:
        raise HTTPException(status_code=422, detail=f"Role must be one of {', '.join(ORG_ROLES)}.")
    email = normalize_email(payload.email)
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    inv, token = create_invite(db, org.id, email, payload.role, principal.user)
    link = invite_link(token)
    result = send_email(email, f"You are invited to {org.name}",
                        f"Open this link to join {org.name}: {link}\nIt expires in 14 days.")
    return InviteOut(invite_id=inv.id, email=inv.email, role=inv.role, organization_id=org.id, link=link,
                     expires_at=inv.expires_at, delivered=result.delivered, delivery_note=result.reason)


@router.get("/invites/{token}", response_model=InvitePublic)
def read_invite(token: str, db: Session = Depends(get_db)):
    inv = find_invite(db, token)
    if inv is None:
        raise HTTPException(status_code=404, detail="This invite link is not valid.")
    org = db.get(Organization, inv.organization_id)
    existing = db.query(User.id).filter_by(email=inv.email).first() is not None
    return InvitePublic(organization_name=org.name if org else "", email=inv.email, role=inv.role,
                        state=invite_state(inv), existing_user=existing)


@router.post("/invites/{token}/accept", response_model=LoginOut)
def accept_invite(token: str, payload: InviteAccept, request: Request, db: Session = Depends(get_db)):
    inv = find_invite(db, token)
    if inv is None:
        raise HTTPException(status_code=404, detail="This invite link is not valid.")
    state = invite_state(inv)
    if state != "open":
        raise HTTPException(status_code=410, detail=f"This invite has {state}. Ask for a new one.")
    org = db.get(Organization, inv.organization_id)
    if org is None or not org.is_active:
        raise HTTPException(status_code=410, detail="That organization is no longer active.")
    user = db.query(User).filter_by(email=inv.email).first()
    if user is not None:
        if not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="This email already has an account. Enter its password to accept.")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="This account is disabled.")
    else:
        problem = password_problem(payload.password)
        if problem:
            raise HTTPException(status_code=422, detail=problem)
        user = create_user(db, inv.email, payload.password, payload.name)
    set_membership(db, user, org.id, inv.role)
    inv.accepted_at = datetime.utcnow()
    user.last_login_at = datetime.utcnow()
    db.commit()
    session_token = create_session(db, user, request.headers.get("user-agent"))
    me = _me(db, _principal_for_login(db, user))
    return LoginOut(token=session_token, **me.model_dump())


@router.delete("/invites/{invite_id}")
def revoke_invite(invite_id: int, db: Session = Depends(get_db),
                  principal: Principal = Depends(current_principal)):
    inv = db.get(Invite, invite_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Invite not found.")
    require_org_role(principal, inv.organization_id, ROLE_OWNER)
    db.delete(inv)
    db.commit()
    return {"status": "revoked", "invite_id": invite_id}


# --- password resets ----------------------------------------------------------------


@router.post("/reset/request")
def request_reset(payload: ResetRequest, request: Request, db: Session = Depends(get_db)):
    """Always 200: never confirms whether an email has an account."""
    email = normalize_email(payload.email)
    key = _client_key(request, email)
    if not reset_limiter.allowed(key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
    reset_limiter.hit(key)
    user = db.query(User).filter_by(email=email, is_active=True).first()
    delivered = False
    if user is not None:
        _, token = create_reset(db, user)
        delivered = send_email(email, "Reset your password",
                               f"Open this link to choose a new password: {reset_link(token)}\n"
                               "It expires in 24 hours.").delivered
    return {"status": "ok", "delivered": delivered,
            "note": "If that email has an account and email is configured, a link is on its way. "
                    "Otherwise ask your organization owner for a reset link."}


@router.post("/users/{user_id}/reset-link")
def admin_reset_link(user_id: int, db: Session = Depends(get_db),
                     principal: Principal = Depends(current_principal)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if not principal.is_platform_admin:
        shared = [m.organization_id for m in db.query(OrgMembership).filter_by(user_id=user.id).all()]
        if not any(principal.role_in(oid) == ROLE_OWNER for oid in shared):
            raise HTTPException(status_code=403, detail="Only an owner of one of this user's organizations can do that.")
    _, token = create_reset(db, user)
    link = reset_link(token)
    result = send_email(user.email, "Reset your password", f"Open this link to choose a new password: {link}")
    return {"user_id": user.id, "email": user.email, "link": link, "delivered": result.delivered,
            "delivery_note": result.reason}


@router.get("/reset/{token}")
def read_reset(token: str, db: Session = Depends(get_db)):
    reset = find_open_reset(db, token)
    if reset is None:
        return {"valid": False, "email": None}
    user = db.get(User, reset.user_id)
    return {"valid": user is not None and user.is_active, "email": user.email if user else None}


@router.post("/reset/{token}/confirm")
def confirm_reset(token: str, payload: ResetConfirm, db: Session = Depends(get_db)):
    reset = find_open_reset(db, token)
    if reset is None:
        raise HTTPException(status_code=410, detail="This reset link is not valid any more. Ask for a new one.")
    problem = password_problem(payload.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    user = db.get(User, reset.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=410, detail="This account is not active.")
    user.password_hash = hash_password(payload.password)
    reset.used_at = datetime.utcnow()
    db.commit()
    revoke_all_sessions(db, user.id)
    return {"status": "reset", "email": user.email}


# --- team -----------------------------------------------------------------------------


@router.get("/orgs/{org_id}/members", response_model=MembersOut)
def list_members(org_id: int, db: Session = Depends(get_db),
                 principal: Principal = Depends(current_principal)):
    require_org_role(principal, org_id, "viewer")
    rows = (
        db.query(OrgMembership, User)
        .join(User, User.id == OrgMembership.user_id)
        .filter(OrgMembership.organization_id == org_id, User.is_active.is_(True))
        .order_by(User.email)
        .all()
    )
    pending = (
        db.query(Invite)
        .filter(Invite.organization_id == org_id, Invite.accepted_at.is_(None), Invite.expires_at > datetime.utcnow())
        .order_by(Invite.created_at.desc())
        .all()
    )
    return MembersOut(
        organization_id=org_id,
        members=[MemberOut(user_id=u.id, email=u.email, name=u.name, role=m.role, last_login_at=u.last_login_at)
                 for m, u in rows],
        pending_invites=[PendingInviteOut(invite_id=i.id, email=i.email, role=i.role, expires_at=i.expires_at)
                         for i in pending],
    )


def _owner_count(db: Session, org_id: int) -> int:
    return (
        db.query(OrgMembership)
        .join(User, User.id == OrgMembership.user_id)
        .filter(OrgMembership.organization_id == org_id, OrgMembership.role == ROLE_OWNER, User.is_active.is_(True))
        .count()
    )


@router.patch("/orgs/{org_id}/members/{user_id}")
def change_role(org_id: int, user_id: int, payload: RoleChange, db: Session = Depends(get_db),
                principal: Principal = Depends(current_principal)):
    require_org_role(principal, org_id, ROLE_OWNER)
    if payload.role not in ORG_ROLES:
        raise HTTPException(status_code=422, detail=f"Role must be one of {', '.join(ORG_ROLES)}.")
    m = db.query(OrgMembership).filter_by(organization_id=org_id, user_id=user_id).first()
    if m is None:
        raise HTTPException(status_code=404, detail="That person is not a member of this organization.")
    if m.role == ROLE_OWNER and payload.role != ROLE_OWNER and _owner_count(db, org_id) <= 1:
        raise HTTPException(status_code=409, detail="An organization needs at least one owner.")
    m.role = payload.role
    db.commit()
    return {"organization_id": org_id, "user_id": user_id, "role": m.role}


@router.delete("/orgs/{org_id}/members/{user_id}")
def remove_member(org_id: int, user_id: int, db: Session = Depends(get_db),
                  principal: Principal = Depends(current_principal)):
    require_org_role(principal, org_id, ROLE_OWNER)
    m = db.query(OrgMembership).filter_by(organization_id=org_id, user_id=user_id).first()
    if m is None:
        raise HTTPException(status_code=404, detail="That person is not a member of this organization.")
    if m.role == ROLE_OWNER and _owner_count(db, org_id) <= 1:
        raise HTTPException(status_code=409, detail="An organization needs at least one owner.")
    db.delete(m)
    db.commit()
    return {"status": "removed", "organization_id": org_id, "user_id": user_id}
