"""Create the first administrator without a public registration/backdoor endpoint."""

import argparse
from getpass import getpass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import get_engine
from app.models import Permission, Role, RolePermission, User
from app.schemas.identity import UserCreate
from app.services.authorization import ADMIN_PERMISSIONS, lock_admin_changes


def bootstrap_admin(db: Session, name: str, email: str, password: str) -> User:
    lock_admin_changes(db)
    if db.scalar(select(User.id).limit(1)) is not None:
        raise ValueError("Bootstrap is only allowed before the first user exists")
    # Grant-based selection; role names never imply authorization.
    role_id = db.scalar(
        select(Role.id)
        .join(RolePermission)
        .join(Permission)
        .where(Permission.code.in_(ADMIN_PERMISSIONS))
        .group_by(Role.id)
        .having(func.count(Permission.id) == len(ADMIN_PERMISSIONS))
        .order_by(Role.name)
        .limit(1)
    )
    if role_id is None:
        raise ValueError("Seed the database before bootstrapping an administrator")
    body = UserCreate(name=name, email=email, password=password, role_id=role_id)
    user = User(
        name=body.name,
        email=str(body.email),
        role_id=body.role_id,
        password_hash=hash_password(body.password.get_secret_value()),
    )
    db.add(user)
    db.flush()
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    password = getpass("Admin password (12-128 characters): ")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    try:
        with Session(get_engine()) as db, db.begin():
            bootstrap_admin(db, args.name, args.email, password)
    except ValueError:
        # Do not echo validation inputs, which could include the password.
        raise SystemExit("Bootstrap refused: check input, seed data, or existing users") from None
    print("Administrator created. Sign in through /api/v1/auth/login.")


if __name__ == "__main__":
    main()
