"""One-time creation of the founder's login from environment variables."""

import logging

from app.auth.service import create_user, set_membership
from app.config import settings
from app.db import SessionLocal
from app.models import User
from app.models.user import ROLE_OWNER
from app.services.observatory.tenancy import default_organization_id

log = logging.getLogger(__name__)


def bootstrap_admin() -> User | None:
    email = settings.bootstrap_admin_email.strip().lower()
    password = settings.bootstrap_admin_password
    if not email or not password:
        return None
    db = SessionLocal()
    try:
        existing = db.query(User).filter_by(email=email).first()
        if existing is not None:
            return None
        user = create_user(db, email, password, settings.bootstrap_admin_name, is_platform_admin=True)
        set_membership(db, user, default_organization_id(db), ROLE_OWNER)
        log.info("Bootstrapped platform admin %s", email)
        return user
    finally:
        db.close()
