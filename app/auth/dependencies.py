from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import SESSION_COOKIE, resolve_session
from app.db.engine import get_db
from app.db.models import Role, User
from app.exceptions.exceptions import NotAuthenticatedException, PermissionDeniedException


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Sent by the coordinator page on every request. A cross-site form cannot
# set custom headers, and a cross-site fetch that tries triggers a CORS
# preflight this API never approves -- together with SameSite=Strict
# cookies, that closes off cross-site request forgery.
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "trekxp"


def check_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return

    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise PermissionDeniedException("Missing request verification header.")


async def current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    check_csrf(request)
    user = await resolve_session(db, request.cookies.get(SESSION_COOKIE))

    if user is None:
        raise NotAuthenticatedException("Please sign in.")

    return user


async def require_coordinator(user: User = Depends(current_user)) -> User:
    # Admins can do everything coordinators can.
    if user.role not in (Role.ADMIN, Role.COORDINATOR):
        raise PermissionDeniedException("Coordinator access required.")

    return user


async def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != Role.ADMIN:
        raise PermissionDeniedException("Admin access required.")

    return user
