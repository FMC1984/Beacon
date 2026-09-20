"""Create or update a login from the command line.

    python -m app.cli.create_user --email tina@example.com --name "Tina" --platform-admin
    python -m app.cli.create_user --email client@example.com --org 2 --role viewer

Idempotent on email: an existing user keeps their password unless --password
is given, and gains the membership or platform flag requested. The password is
prompted for when omitted.
"""

import argparse
import getpass
import sys

from app.auth.passwords import hash_password, password_problem
from app.auth.service import create_user, normalize_email, set_membership
from app.db import SessionLocal
from app.models import Organization, User
from app.models.user import ORG_ROLES, ROLE_OWNER
from app.services.observatory.tenancy import default_organization_id


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or update a Beacon login.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--password", default=None, help="Omit to be prompted.")
    parser.add_argument("--platform-admin", action="store_true")
    parser.add_argument("--org", default="default", help="Organization id or slug (default: default).")
    parser.add_argument("--role", default=ROLE_OWNER, choices=ORG_ROLES)
    parser.add_argument("--no-membership", action="store_true", help="Create the user without joining an organization.")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        email = normalize_email(args.email)
        user = db.query(User).filter_by(email=email).first()
        password = args.password
        if user is None and password is None:
            password = getpass.getpass("Password: ")
        if password is not None:
            problem = password_problem(password)
            if problem:
                print(problem, file=sys.stderr)
                return 2
        if user is None:
            user = create_user(db, email, password, args.name, is_platform_admin=args.platform_admin)
            print(f"Created {user.email} (id {user.id}).")
        else:
            if password is not None:
                user.password_hash = hash_password(password)
            if args.name:
                user.name = args.name
            if args.platform_admin:
                user.is_platform_admin = True
            user.is_active = True
            db.commit()
            print(f"Updated {user.email} (id {user.id}).")
        if not args.no_membership:
            if args.org == "default":
                org_id = default_organization_id(db)
            elif args.org.isdigit():
                org_id = int(args.org)
            else:
                org = db.query(Organization).filter_by(slug=args.org).first()
                if org is None:
                    print(f"No organization with slug {args.org!r}.", file=sys.stderr)
                    return 2
                org_id = org.id
            if db.get(Organization, org_id) is None:
                print(f"No organization with id {org_id}.", file=sys.stderr)
                return 2
            m = set_membership(db, user, org_id, args.role)
            print(f"{user.email} is {m.role} of organization {org_id}.")
        if user.is_platform_admin:
            print("Platform admin: sees every organization.")
        return 0
    finally:
        db.close()


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
