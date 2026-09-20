"""Session, invite and password-reset mechanics (no HTTP in here)."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.auth.tokens import hash_token, new_token
from app.config import settings
from app.models import Invite, Organization, OrgMembership, PasswordReset, User, UserSession
from app.models.user import ORG_ROLES

INVITE_DAYS = 14
RESET_HOURS = 24
SESSION_TOUCH_MINUTES = 5


def utcnow() -> datetime:
    return datetime.utcnow()


# --- sessions ------------------------------------------------------------------


def create_session(db: Session, user: User, user_agent: str | None = None) -> str:
    token = new_token()
    now = utcnow()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(days=settings.session_days),
            last_seen_at=now,
            user_agent=(user_agent or "")[:300] or None,
        )
    )
    db.commit()
    return token


def find_session(db: Session, token: str) -> UserSession | None:
    sess = db.query(UserSession).filter_by(token_hash=hash_token(token), revoked_at=None).first()
    if sess is None:
        return None
    now = utcnow()
    if sess.expires_at <= now:
        return None
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        return None
    if sess.last_seen_at is None or sess.last_seen_at < now - timedelta(minutes=SESSION_TOUCH_MINUTES):
        sess.last_seen_at = now
        sess.expires_at = now + timedelta(days=settings.session_days)
        db.commit()
    return sess


def revoke_session(db: Session, token: str) -> None:
    sess = db.query(UserSession).filter_by(token_hash=hash_token(token), revoked_at=None).first()
    if sess is not None:
        sess.revoked_at = utcnow()
        db.commit()


def revoke_all_sessions(db: Session, user_id: int, keep_token: str | None = None) -> int:
    now = utcnow()
    q = db.query(UserSession).filter_by(user_id=user_id, revoked_at=None)
    if keep_token:
        q = q.filter(UserSession.token_hash != hash_token(keep_token))
    n = q.update({UserSession.revoked_at: now}, synchronize_session=False)
    db.commit()
    return n


# --- users and memberships ------------------------------------------------------


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(db: Session, email: str, password: str, name: str | None = None,
                is_platform_admin: bool = False) -> User:
    user = User(email=normalize_email(email), name=(name or "").strip() or None,
                password_hash=hash_password(password), is_platform_admin=is_platform_admin, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def set_membership(db: Session, user: User, organization_id: int, role: str) -> OrgMembership:
    if role not in ORG_ROLES:
        raise ValueError(f"Unknown role {role!r}.")
    m = db.query(OrgMembership).filter_by(user_id=user.id, organization_id=organization_id).first()
    if m is None:
        m = OrgMembership(user_id=user.id, organization_id=organization_id, role=role)
        db.add(m)
    else:
        m.role = role
    db.commit()
    db.refresh(m)
    return m


def memberships_for(db: Session, user: User) -> list[OrgMembership]:
    return (
        db.query(OrgMembership)
        .join(Organization, Organization.id == OrgMembership.organization_id)
        .filter(OrgMembership.user_id == user.id, Organization.is_active.is_(True))
        .order_by(OrgMembership.organization_id)
        .all()
    )


# --- invites --------------------------------------------------------------------


def invite_link(token: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}/invite/{token}"


def reset_link(token: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}/reset/{token}"


def create_invite(db: Session, organization_id: int, email: str, role: str,
                  created_by: User | None) -> tuple[Invite, str]:
    if role not in ORG_ROLES:
        raise ValueError(f"Unknown role {role!r}.")
    token = new_token()
    inv = Invite(
        organization_id=organization_id, email=normalize_email(email), role=role,
        token_hash=hash_token(token), created_by_user_id=created_by.id if created_by else None,
        expires_at=utcnow() + timedelta(days=INVITE_DAYS),
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv, token


def find_invite(db: Session, token: str) -> Invite | None:
    return db.query(Invite).filter_by(token_hash=hash_token(token)).first()


def invite_state(inv: Invite) -> str:
    if inv.accepted_at is not None:
        return "accepted"
    if inv.expires_at <= utcnow():
        return "expired"
    return "open"


# --- password resets ------------------------------------------------------------


def create_reset(db: Session, user: User) -> tuple[PasswordReset, str]:
    token = new_token()
    reset = PasswordReset(user_id=user.id, token_hash=hash_token(token),
                          expires_at=utcnow() + timedelta(hours=RESET_HOURS))
    db.add(reset)
    db.commit()
    db.refresh(reset)
    return reset, token


def find_open_reset(db: Session, token: str) -> PasswordReset | None:
    reset = db.query(PasswordReset).filter_by(token_hash=hash_token(token), used_at=None).first()
    if reset is None or reset.expires_at <= utcnow():
        return None
    return reset
