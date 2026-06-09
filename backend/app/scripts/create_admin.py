import argparse
import uuid

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User
from app.models.workspace import Workspace
from app.roles import VALID_ROLES, normalize_role


def create_default_workspace(db) -> Workspace:
    workspace = db.query(Workspace).filter(Workspace.slug == "default").first()
    if workspace:
        return workspace
    workspace = Workspace(id=uuid.uuid4(), name="Default Workspace", slug="default")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def create_admin(db, email: str, password: str, name: str, role: str = "admin") -> User:
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        print(f"User with email {email} already exists.")
        return existing

    create_default_workspace(db)

    normalized_role = normalize_role(role)
    if normalized_role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Expected one of: {', '.join(sorted(VALID_ROLES))}")

    user = User(
        id=uuid.uuid4(),
        email=email,
        name=name,
        password_hash=hash_password(password),
        role=normalized_role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"{normalized_role.title()} user {email} created successfully.")
    return user


def main():
    parser = argparse.ArgumentParser(description="Create an admin user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=sorted(VALID_ROLES), default="admin")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        create_admin(db, args.email, args.password, args.name, args.role)
    finally:
        db.close()


if __name__ == "__main__":
    main()
