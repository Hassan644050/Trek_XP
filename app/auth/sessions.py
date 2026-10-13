import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_auth_settings
from app.db.models import AuthSession, User
from app.exceptions.exceptions import AccountLockedException, InvalidCredentialsException
from app.auth.passwords import hash_password, needs_rehash, verify_password


SESSION_COOKIE = "trekxp_session"


def _now() -> datetime:
    return datetime.now(UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    """Check credentials, applying the failed-attempt lockout.

    Every rejection says the same thing ("invalid email or password") so the
    response does not reveal whether an account exists. Only a locked
    account says so, because the owner needs to know to wait.
    """
    settings = get_auth_settings()
    user = await db.scalar(select(User).where(User.email == normalize_email(email)))

    if user is not None and user.locked_until and user.locked_until > _now():
        raise AccountLockedException(
            "Too many failed sign-in attempts. Try again later."
        )

    # Always run a verify, even for unknown emails (see verify_password).
    valid = verify_password(user.password_hash if user else None, password)

    if user is None or not user.is_active or not valid:
        if user is not None and user.is_active:
            user.failed_logins += 1

            if user.failed_logins >= settings.max_failed_logins:
                user.locked_until = _now() + timedelta(minutes=settings.lockout_minutes)
                user.failed_logins = 0

            await db.commit()

        raise InvalidCredentialsException("Invalid email or password.")

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = _now()

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    return user


async def start_session(db: AsyncSession, user: User) -> tuple[str, datetime]:
    """Create a session and return the raw cookie token (never stored)."""
    token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(hours=get_auth_settings().session_hours)

    db.add(AuthSession(user_id=user.id, token_hash=hash_token(token), expires_at=expires_at))
    await db.commit()

    return token, expires_at


async def resolve_session(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None

    session = await db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_token(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > _now(),
        )
    )

    if session is None or not session.user.is_active:
        return None

    return session.user


async def end_session(db: AsyncSession, token: str | None) -> None:
    if not token:
        return

    await db.execute(
        update(AuthSession)
        .where(AuthSession.token_hash == hash_token(token), AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()


async def end_all_sessions(db: AsyncSession, user_id: int) -> None:
    """Sign a user out everywhere -- on deactivation or password reset."""
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
