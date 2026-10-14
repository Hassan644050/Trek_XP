from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.auth.passwords import hash_password, password_problem
from app.auth.sessions import end_all_sessions, normalize_email
from app.db.engine import get_db
from app.db.models import Role, User
from app.exceptions.exceptions import (
    InvalidInputException,
    PermissionDeniedException,
    ResourceConflictException,
    ResourceNotFoundException,
)
from app.models.catalog import UserCreate, UserOut, UserUpdate


router = APIRouter(prefix="/api/admin", tags=["admin"])


def _checked_password(password: str) -> str:
    problem = password_problem(password)

    if problem:
        raise InvalidInputException(problem)

    return hash_password(password)


@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[User]:
    return list((await db.scalars(select(User).order_by(User.role, User.name))).all())


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> User:
    email = normalize_email(payload.email)
    conflict = f"An account for {email} already exists."

    if await db.scalar(select(User.id).where(User.email == email)):
        raise ResourceConflictException(conflict)

    user = User(
        email=email,
        name=payload.name,
        password_hash=_checked_password(payload.password),
        role=payload.role,
    )
    db.add(user)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ResourceConflictException(conflict) from exc

    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = await db.get(User, user_id)

    if user is None:
        raise ResourceNotFoundException("That account no longer exists.")

    # An admin who demotes or deactivates themself can lock everyone out
    # of account management; that has to be done by another admin.
    if user.id == admin.id and (
        payload.is_active is False or (payload.role is not None and payload.role != Role.ADMIN)
    ):
        raise PermissionDeniedException("You cannot deactivate or demote your own account.")

    if payload.name is not None:
        user.name = " ".join(payload.name.split())

    if payload.role is not None:
        user.role = payload.role

    sign_out_everywhere = False

    if payload.is_active is not None:
        if not payload.is_active and user.is_active:
            sign_out_everywhere = True

        user.is_active = payload.is_active

        if payload.is_active:
            # Reactivation also clears any lockout in progress.
            user.failed_logins = 0
            user.locked_until = None

    if payload.password is not None:
        user.password_hash = _checked_password(payload.password)
        user.failed_logins = 0
        user.locked_until = None
        sign_out_everywhere = True

    if sign_out_everywhere:
        await end_all_sessions(db, user.id)

    await db.commit()

    return user


# ---------- catalog settings: trip types, activities, divisions, destinations ----------

from sqlalchemy import func

from app.db.models import ActivityOption, Division, Place, Placement, TripTypeOption
from app.models.catalog import (
    DestinationCreate,
    DestinationRow,
    DivisionCreate,
    DivisionRow,
    OptionAdmin,
    OptionCreate,
    OptionUpdate,
)
from app.services.destination.countries import home_country
from app.services.taxonomy import add_division, add_option, list_options

_OPTION_MODELS = {"trip-types": TripTypeOption, "activities": ActivityOption}


def _option_model(kind: str):
    model = _OPTION_MODELS.get(kind)
    if model is None:
        raise ResourceNotFoundException("Unknown option list.")
    return model


@router.get("/options/{kind}", response_model=list[OptionAdmin])
async def list_option_kind(
    kind: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list:
    return await list_options(db, _option_model(kind), active_only=False)


@router.post("/options/{kind}", response_model=OptionAdmin, status_code=201)
async def create_option(
    kind: str,
    payload: OptionCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    option = await add_option(db, _option_model(kind), payload.label)

    if option is None:
        raise InvalidInputException("That name has no letters or digits to make a value from.")

    await db.commit()
    return option


@router.patch("/options/{kind}/{option_id}", response_model=OptionAdmin)
async def update_option(
    kind: str,
    option_id: int,
    payload: OptionUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    option = await db.get(_option_model(kind), option_id)

    if option is None:
        raise ResourceNotFoundException("That option no longer exists.")

    if payload.label is not None:
        option.label = " ".join(payload.label.split())

    if payload.is_active is not None:
        option.is_active = payload.is_active

    await db.commit()
    return option


@router.get("/divisions", response_model=list[DivisionRow])
async def list_division_rows(
    country: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list:
    code = (country or home_country().code).upper()
    return list(
        (
            await db.scalars(
                select(Division).where(Division.country_code == code)
                .order_by(Division.sort_order, Division.name)
            )
        ).all()
    )


@router.post("/divisions", response_model=DivisionRow, status_code=201)
async def create_division(
    payload: DivisionCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    code = (payload.country_code or home_country().code).upper()
    division = await add_division(db, code, payload.name)

    if division is None:
        raise InvalidInputException("A division needs a name.")

    await db.commit()
    return division


@router.delete("/divisions/{division_id}", status_code=204)
async def delete_division(
    division_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    division = await db.get(Division, division_id)

    if division is not None:
        await db.delete(division)
        await db.commit()


def _destination_row(place: Place, placements: int) -> DestinationRow:
    return DestinationRow(
        id=place.id, name=place.name, latitude=place.latitude, longitude=place.longitude,
        division=place.division, country_code=place.country_code, placement_count=placements,
    )


@router.get("/destinations", response_model=list[DestinationRow])
async def list_destinations(
    country: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[DestinationRow]:
    code = (country or home_country().code).upper()
    rows = (
        await db.execute(
            select(Place, func.count(Placement.id))
            .outerjoin(Placement, Placement.place_id == Place.id)
            .where(Place.country_code == code)
            .group_by(Place.id)
            .order_by(Place.division, Place.name)
        )
    ).all()

    return [_destination_row(place, count) for place, count in rows]


@router.post("/destinations", response_model=DestinationRow, status_code=201)
async def create_destination(
    payload: DestinationCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> DestinationRow:
    code = (payload.country_code or home_country().code).upper()
    country = home_country()

    existing = await db.scalar(
        select(Place).where(
            Place.name == payload.name,
            Place.latitude == payload.latitude,
            Place.longitude == payload.longitude,
        )
    )
    if existing is not None:
        raise ResourceConflictException(f"'{payload.name}' is already a destination.")

    place = Place(
        name=payload.name, country_code=code,
        country_name=country.name if code == country.code else None,
        latitude=payload.latitude, longitude=payload.longitude, division=payload.division,
    )
    db.add(place)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ResourceConflictException(f"'{payload.name}' is already a destination.") from exc

    return _destination_row(place, 0)


@router.delete("/destinations/{place_id}", status_code=204)
async def delete_destination(
    place_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    place = await db.get(Place, place_id)

    if place is None:
        return

    in_use = await db.scalar(
        select(func.count()).select_from(Placement).where(Placement.place_id == place_id)
    )
    if in_use:
        raise ResourceConflictException(
            f"'{place.name}' has {in_use} gadget placement(s); remove them first."
        )

    await db.delete(place)
    await db.commit()
