"""Run once after migrations. Repeat runs never restore revoked grants."""

from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.models import Category, Permission, Role, RoleCategoryAccess, RolePermission

CATEGORIES = ("General", "Engineering", "HR", "Finance", "Management")
GRANTS = {
    "Employee": ("General",),
    "Engineer": ("General", "Engineering"),
    "HR": ("General", "HR"),
    "Finance": ("General", "Finance"),
    "Manager": ("General", "Management"),
    "Admin": CATEGORIES,
}
PERMISSIONS = ("users.manage", "roles.manage", "documents.manage")


def seed_id(kind: str, name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://securerag.local/seed/{kind}/{name}")


def seed_initial(session: Session) -> None:
    for category in CATEGORIES:
        session.execute(
            insert(Category)
            .values(
                id=seed_id("category", category),
                name=category,
            )
            .on_conflict_do_nothing()
        )
    for code in PERMISSIONS:
        session.execute(
            insert(Permission)
            .values(
                id=seed_id("permission", code),
                code=code,
            )
            .on_conflict_do_nothing()
        )
    for name, categories in GRANTS.items():
        role_id = session.execute(
            insert(Role)
            .values(
                id=seed_id("role", name),
                name=name,
            )
            .on_conflict_do_nothing()
            .returning(Role.id)
        ).scalar_one_or_none()
        if role_id is None:
            continue  # Existing roles keep their administrator-managed grants.
        for category in categories:
            session.execute(
                insert(RoleCategoryAccess).values(
                    role_id=role_id,
                    category_id=seed_id("category", category),
                )
            )
        if name == "Admin":
            for code in PERMISSIONS:
                session.execute(
                    insert(RolePermission).values(
                        role_id=role_id,
                        permission_id=seed_id("permission", code),
                    )
                )


def main() -> None:
    with Session(get_engine()) as session, session.begin():
        seed_initial(session)
    print("Initial roles/categories seeded; existing role grants were preserved.")


if __name__ == "__main__":
    main()
