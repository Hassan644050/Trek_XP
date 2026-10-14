import asyncio
import logging

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_coordinator
from app.config import get_env_meta_info
from app.db.engine import get_db
from app.db.models import Gadget, Placement, Place, User
from app.exceptions.exceptions import ResourceConflictException, ResourceNotFoundException
from app.models.catalog import (
    AdminAreasOut,
    CatalogOptions,
    DivisionOut,
    ManualPlaceIn,
    GadgetDetail,
    GadgetIn,
    GadgetOut,
    GadgetUpdate,
    PlaceIn,
    PlaceOut,
    PlacementIn,
    PlacementOut,
    PlacementUpdate,
)
from app.models.recommendation import Priority
from app.models.trip import Activity, TripType
from app.services.destination.admin_areas import (
    ADMIN_COUNTRY,
    district_names,
    divisions,
    find_district,
)
from app.services.destination.geocode import geocode
from app.services.media.images import MAX_UPLOAD_BYTES, process_image
from app.services.media.storage import get_image_storage, new_image_key


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/coordinator", tags=["coordinator"])


# ---------- image side effects ----------
#
# Storage is blocking I/O -- a put to R2 is a network round trip -- so every
# call goes to a worker thread rather than stalling the event loop.


async def _store_image(storage, key: str, data: bytes) -> None:
    await asyncio.to_thread(storage.save, key, data)


async def _discard_image(storage, key: str) -> None:
    """Delete an image we no longer want, best effort.

    Called only once the database says so. A leftover object wastes a few
    kilobytes; failing the request would report an error for work that has
    already succeeded, or hide the error that triggered the cleanup.
    """
    try:
        await asyncio.to_thread(storage.delete, key)
    except Exception:
        logger.warning("Could not delete image %s", key, exc_info=True)


# ---------- serialization ----------


def _placement_out(placement: Placement) -> PlacementOut:
    return PlacementOut(
        id=placement.id,
        place=placement.place,
        trip_types=placement.trip_types,
        activities=placement.activities,
        priority=placement.priority,
        why=placement.why,
        updated_at=placement.updated_at,
    )


def _gadget_out(gadget: Gadget) -> GadgetOut:
    return GadgetOut(
        id=gadget.id,
        name=gadget.name,
        category=gadget.category,
        description=gadget.description,
        image_url=get_image_storage().url(gadget.image_key) if gadget.image_key else None,
        placement_count=len(gadget.placements),
        updated_at=gadget.updated_at,
    )


def _gadget_detail(gadget: Gadget) -> GadgetDetail:
    return GadgetDetail(
        **_gadget_out(gadget).model_dump(),
        placements=[_placement_out(p) for p in gadget.placements],
    )


# ---------- lookups ----------


async def _load_gadget(db: AsyncSession, gadget_id: int) -> Gadget:
    gadget = await db.scalar(
        select(Gadget)
        .where(Gadget.id == gadget_id)
        .options(selectinload(Gadget.placements).joinedload(Placement.place))
        .execution_options(populate_existing=True)
    )

    if gadget is None:
        raise ResourceNotFoundException("That gadget no longer exists.")

    return gadget


async def _load_placement(db: AsyncSession, placement_id: int) -> Placement:
    placement = await db.get(Placement, placement_id)

    if placement is None:
        raise ResourceNotFoundException("That placement no longer exists.")

    return placement


async def _name_taken(db: AsyncSession, name: str, except_id: int | None = None) -> bool:
    query = select(Gadget.id).where(func.lower(Gadget.name) == name.lower())

    if except_id is not None:
        query = query.where(Gadget.id != except_id)

    return await db.scalar(query) is not None


async def _upsert_place(db: AsyncSession, place: PlaceIn) -> Place:
    """One row per picked place, however many coordinators pick it.

    INSERT ... ON CONFLICT DO NOTHING then SELECT, so two simultaneous
    saves of the same new place cannot both insert it.
    """
    values = place.model_dump()

    await db.execute(
        insert(Place).values(**values).on_conflict_do_nothing(
            constraint="uq_places_name_coords"
        )
    )

    return await db.scalar(
        select(Place).where(
            Place.name == place.name,
            Place.latitude == place.latitude,
            Place.longitude == place.longitude,
        )
    )


async def _commit_or_conflict(db: AsyncSession, message: str) -> None:
    # The pre-checks give friendly errors; the database constraint is the
    # real guarantee when two coordinators save at the same moment.
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ResourceConflictException(message) from exc


# ---------- options ----------


@router.get("/options", response_model=CatalogOptions)
async def options(_: User = Depends(require_coordinator)) -> CatalogOptions:
    return CatalogOptions(
        trip_types=[t.value for t in TripType],
        activities=[a.value for a in Activity],
        priorities=[p.value for p in Priority],
    )


# ---------- places ----------


def _escape_like(term: str) -> str:
    # Escape LIKE wildcards so a search for "100%" means what it says.
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/places", response_model=list[PlaceOut])
async def saved_places(
    q: str = Query(min_length=2, max_length=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_coordinator),
) -> list[Place]:
    """Places coordinators have used before -- instant, and includes
    landmarks the type-ahead geocoder does not know."""
    places = await db.scalars(
        select(Place)
        .where(Place.name.ilike(f"%{_escape_like(q.strip())}%", escape="\\"))
        .order_by(Place.name)
        .limit(6)
    )

    return list(places.all())


@router.get("/places/lookup", response_model=PlaceIn)
async def lookup_place(
    q: str = Query(min_length=2, max_length=100),
    _: User = Depends(require_coordinator),
) -> PlaceIn:
    """Full geocoding chain, OpenStreetMap included, for one explicit
    search. Called on a button press, never per keystroke: OpenStreetMap's
    usage policy forbids type-ahead."""
    found = await geocode(q.strip(), home_country=get_env_meta_info().home_country)

    if found is None:
        raise ResourceNotFoundException(
            f"No place called '{q.strip()}' was found. Try the nearest town."
        )

    return PlaceIn(
        name=found.name,
        country_code=found.country_code,
        country_name=found.country,
        latitude=found.latitude,
        longitude=found.longitude,
    )


@router.get("/admin-areas", response_model=AdminAreasOut)
async def admin_areas(_: User = Depends(require_coordinator)) -> AdminAreasOut:
    """Divisions and districts for the manual-entry dropdowns."""
    return AdminAreasOut(
        divisions=[
            DivisionOut(name=division, districts=district_names(division))
            for division in divisions()
        ]
    )


@router.post("/places/manual", response_model=PlaceIn)
async def manual_place(
    payload: ManualPlaceIn,
    _: User = Depends(require_coordinator),
) -> PlaceIn:
    """Build a place from a name and a district.

    For spots no geocoder knows -- Sada Pathor, Bichanakandi and the like.
    The district supplies the coordinates, so the climate lookup lands in
    the right place even though the exact spot is unmapped.
    """
    district = find_district(payload.district)

    if district is None:
        raise ResourceNotFoundException(f"'{payload.district}' is not a district we know.")

    return PlaceIn(
        name=payload.name,
        country_code=ADMIN_COUNTRY,
        country_name="Bangladesh",
        latitude=district.latitude,
        longitude=district.longitude,
        district=district.name,
        division=district.division,
    )


# ---------- gadgets ----------


@router.get("/gadgets", response_model=list[GadgetOut])
async def list_gadgets(
    q: str | None = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_coordinator),
) -> list[GadgetOut]:
    query = select(Gadget).options(selectinload(Gadget.placements)).order_by(Gadget.name)

    if q and q.strip():
        query = query.where(Gadget.name.ilike(f"%{_escape_like(q.strip())}%", escape="\\"))

    gadgets = (await db.scalars(query)).all()

    return [_gadget_out(g) for g in gadgets]


@router.post("/gadgets", response_model=GadgetDetail, status_code=201)
async def create_gadget(
    payload: GadgetIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_coordinator),
) -> GadgetDetail:
    conflict = f"A gadget called '{payload.name}' already exists."

    if await _name_taken(db, payload.name):
        raise ResourceConflictException(conflict)

    gadget = Gadget(**payload.model_dump(), created_by_id=user.id, updated_by_id=user.id)
    db.add(gadget)
    await _commit_or_conflict(db, conflict)

    return _gadget_detail(await _load_gadget(db, gadget.id))


@router.get("/gadgets/{gadget_id}", response_model=GadgetDetail)
async def get_gadget(
    gadget_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_coordinator),
) -> GadgetDetail:
    return _gadget_detail(await _load_gadget(db, gadget_id))


@router.patch("/gadgets/{gadget_id}", response_model=GadgetDetail)
async def update_gadget(
    gadget_id: int,
    payload: GadgetUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_coordinator),
) -> GadgetDetail:
    gadget = await _load_gadget(db, gadget_id)
    changes = payload.model_dump(exclude_unset=True)

    if not changes.get("name", True):
        changes.pop("name")

    conflict = f"A gadget called '{changes.get('name')}' already exists."

    if "name" in changes and await _name_taken(db, changes["name"], except_id=gadget.id):
        raise ResourceConflictException(conflict)

    for field, value in changes.items():
        setattr(gadget, field, value)

    gadget.updated_by_id = user.id
    await _commit_or_conflict(db, conflict)

    return _gadget_detail(await _load_gadget(db, gadget_id))


@router.delete("/gadgets/{gadget_id}", status_code=204)
async def delete_gadget(
    gadget_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_coordinator),
) -> None:
    gadget = await _load_gadget(db, gadget_id)
    image_key = gadget.image_key

    await db.delete(gadget)
    await db.commit()

    # File removed only after the row is gone: a failed delete must not
    # leave a gadget pointing at a missing image.
    if image_key:
        await _discard_image(get_image_storage(), image_key)


# ---------- images ----------


@router.put("/gadgets/{gadget_id}/image", response_model=GadgetDetail)
async def upload_image(
    gadget_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_coordinator),
) -> GadgetDetail:
    gadget = await _load_gadget(db, gadget_id)

    # Read one byte past the limit: enough to know it is too big without
    # holding an arbitrarily large upload in memory.
    data = await file.read(MAX_UPLOAD_BYTES + 1)

    # Decoding and re-encoding is CPU-bound; keep it off the event loop.
    processed = await asyncio.to_thread(process_image, data)

    storage = get_image_storage()
    new_key = new_image_key()
    old_key = gadget.image_key

    await _store_image(storage, new_key, processed)

    gadget.image_key = new_key
    gadget.updated_by_id = user.id

    try:
        await db.commit()
    except Exception:
        await _discard_image(storage, new_key)
        raise

    if old_key:
        await _discard_image(storage, old_key)

    return _gadget_detail(await _load_gadget(db, gadget_id))


@router.delete("/gadgets/{gadget_id}/image", response_model=GadgetDetail)
async def remove_image(
    gadget_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_coordinator),
) -> GadgetDetail:
    gadget = await _load_gadget(db, gadget_id)
    old_key = gadget.image_key

    gadget.image_key = None
    gadget.updated_by_id = user.id
    await db.commit()

    if old_key:
        await _discard_image(get_image_storage(), old_key)

    return _gadget_detail(await _load_gadget(db, gadget_id))


# ---------- placements ----------


@router.post("/gadgets/{gadget_id}/placements", response_model=GadgetDetail, status_code=201)
async def add_placement(
    gadget_id: int,
    payload: PlacementIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_coordinator),
) -> GadgetDetail:
    await _load_gadget(db, gadget_id)
    place = await _upsert_place(db, payload.place)

    db.add(
        Placement(
            gadget_id=gadget_id,
            place_id=place.id,
            trip_types=[t.value for t in payload.trip_types],
            activities=[a.value for a in payload.activities],
            priority=payload.priority,
            why=payload.why,
            created_by_id=user.id,
            updated_by_id=user.id,
        )
    )
    await db.commit()

    return _gadget_detail(await _load_gadget(db, gadget_id))


@router.patch("/placements/{placement_id}", response_model=GadgetDetail)
async def update_placement(
    placement_id: int,
    payload: PlacementUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_coordinator),
) -> GadgetDetail:
    placement = await _load_placement(db, placement_id)
    changes = payload.model_dump(exclude_unset=True)

    if payload.place is not None:
        placement.place_id = (await _upsert_place(db, payload.place)).id

    if payload.trip_types is not None:
        placement.trip_types = [t.value for t in payload.trip_types]

    if "activities" in changes:
        placement.activities = [a.value for a in payload.activities or []]

    if payload.priority is not None:
        placement.priority = payload.priority

    if payload.why is not None:
        placement.why = " ".join(payload.why.split())

    placement.updated_by_id = user.id
    gadget_id = placement.gadget_id
    await db.commit()

    return _gadget_detail(await _load_gadget(db, gadget_id))


@router.delete("/placements/{placement_id}", response_model=GadgetDetail)
async def delete_placement(
    placement_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_coordinator),
) -> GadgetDetail:
    placement = await _load_placement(db, placement_id)
    gadget_id = placement.gadget_id

    await db.delete(placement)
    await db.commit()

    return _gadget_detail(await _load_gadget(db, gadget_id))
