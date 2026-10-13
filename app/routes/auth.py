from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import check_csrf, current_user
from app.auth.sessions import SESSION_COOKIE, authenticate, end_session, start_session
from app.config import get_auth_settings
from app.db.engine import get_db
from app.db.models import User
from app.models.catalog import LoginRequest, UserOut


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> User:
    # Login gets the same header check as other writes, so another site
    # cannot silently sign a visitor into an account of its choosing.
    check_csrf(request)

    user = await authenticate(db, payload.email, payload.password)
    token, expires_at = await start_session(db, user)

    response.set_cookie(
        SESSION_COOKIE,
        token,
        expires=expires_at,
        httponly=True,  # page scripts cannot read it, so XSS cannot steal it
        secure=get_auth_settings().cookie_secure,
        samesite="strict",
        path="/",
    )

    return user


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    check_csrf(request)
    await end_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> User:
    return user
