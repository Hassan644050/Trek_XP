"""Create (or reset) an admin account from the terminal.

    python -m scripts.create_admin

There is deliberately no sign-up page: coordinators are created by an
admin in the coordinator area, and the first admin is created here, by
someone with access to the server and its DATABASE_URL.
"""

import asyncio
import getpass
import sys

from sqlalchemy import select

from app.auth.passwords import hash_password, password_problem
from app.auth.sessions import end_all_sessions, normalize_email
from app.db.engine import get_engine, get_sessionmaker
from app.db.models import Role, User
from app.models.catalog import UserCreate


def _ask_password() -> str:
    while True:
        password = getpass.getpass("Password (input hidden): ")
        problem = password_problem(password)

        if problem:
            print(problem)
            continue

        if getpass.getpass("Repeat password: ") != password:
            print("Passwords did not match.")
            continue

        return password


async def main() -> int:
    email = normalize_email(input("Admin email: "))
    name = input("Admin name: ").strip()

    # Reuse the API's validation so a bad address fails the same way here.
    try:
        UserCreate(email=email, name=name, password="x" * 10)
    except ValueError as exc:
        print(f"Invalid details: {exc}")
        return 1

    password = _ask_password()

    async with get_sessionmaker()() as db:
        user = await db.scalar(select(User).where(User.email == email))

        if user is None:
            db.add(User(email=email, name=name, password_hash=hash_password(password), role=Role.ADMIN))
            action = "Created"
        else:
            # Recovery path for a forgotten admin password.
            user.name = name or user.name
            user.password_hash = hash_password(password)
            user.role = Role.ADMIN
            user.is_active = True
            user.failed_logins = 0
            user.locked_until = None
            await end_all_sessions(db, user.id)
            action = "Reset"

        await db.commit()

    await get_engine().dispose()
    print(f"{action} admin account for {email}. Sign in at /coordinator.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
