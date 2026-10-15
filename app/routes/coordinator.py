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
from app.db.models import ActivityOption, Gadget, Placement, Place, TripTypeOption, User
from app.exceptions.exceptions import (
    InvalidInputException,
    ResourceConflictException,
    ResourceNotFoundException,
)
from app.models.catalog import (
    Option,
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
from app.services.destination.countries import home_country
from app.services.taxonomy import active_values, list_options
from app.services.slug import unique_gadget_slug
from app.services.destination.admin_areas import (
    district_names,
    divisions,
    find_district,
)
from app.services.destination.geocode import geocode
from app.services.media.images import MAX_UPLOAD_BYTES, process_image
from app.services.media.storage import (
    all_keys,
    get_image_storage,
    new_image_key,
    variant_key,
)
from app.services.media.variants import DETAIL, FULL, THUMB


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/coordinator", tags=["coordinator"])


# ---------- image side effects ----------
#
# Storage is blocking I/O -- a put to R2 is a network round trip -- so every
# call goes to a worker thread rather than stalling the event loop.


async def _store_image_set(storage, key: str, renditions: dict[str, bytes]) -> None:
    """Save every rendition, or leave nothing behind.

    A half-written set would show the listing a thumbnail that 404s, so a
    failure part way through takes the ones already written with it before
    the error propagates.
    """
    written: list[str] = []

    try:
        for variant, data in renditions.items():
            target = variant_key(key, variant)
            await asyncio.to_thread(storage.save, target, data)
            written.append(target)
    except Exception:
        for target in written:
            await _discard_image(storage, target)
        raise


async def _discard_image(storage, key: str) -> None:
    """Delete one stored object we no longer want, best effort.

    Called only once the database says so. A leftover object wastes a few
    kilobytes; failing the request would report an error for work that has
    already succeeded, or hide the error that triggered the cleanup.
    """
    try:
        await asyncio.to_thread(storage.delete, key)
    except Exception:
        logger.warning("Could not delete image %s", key, exc_info=True)


async def _discard_image_set(storage, key: str) -> None:
    """Every rendition of one upload."""
    for target in all_keys(key):
        await _discard_image(storage, target)


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


def _rendition_urls(image_key: str | None) -> dict[str, str | None]:
    """A URL per rendition, or None throughout when there is no image."""
    if not image_key:
        return {"thumb_url": None, "detail_url": None, "image_url": None}

    storage = get_image_storage()

    return {
        "thumb_url": storage.url(variant_key(image_key, THUMB.name)),
        "detail_url": storage.url(variant_key(image_key, DETAIL.name)),
        "image_url": storage.url(variant_key(image_key, FULL.name)),
    }


def _gadget_out(gadget: Gadget) -> GadgetOut:
    return GadgetOut(
        id=gadget.id,
        name=gadget.name,
        brand=gadget.brand,
        model_name=gadget.model_name,
        category=gadget.category,
        color=gadget.color,
        description=gadget.description,
        is_active=gadget.is_active,
        **_rendition_urls(gadget.image_key),
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
async def options(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_coordinator),
) -> CatalogOptions:
    trip_types = await list_options(db, TripTypeOption, active_only=True)
    activities = await list_options(db, ActivityOption, active_only=True)

    return CatalogOptions(
        trip_types=[Option(value=o.value, label=o.label) for o in trip_types],
        activities=[Option(value=o.value, label=o.label) for o in activities],
        priorities=[p.value for p in Priority],
    )


async def _check_taxonomy(db, trip_types, activities) -> None:
    """Reject placement values the admin has not defined (or has retired)."""
    valid_tt = await active_values(db, TripTypeOption)
    valid_ac = await active_values(db, ActivityOption)
    unknown = [t for t in (trip_types or []) if t not in valid_tt]
    unknown += [a for a in (activities or []) if a not in valid_ac]

    if unknown:
        raise InvalidInputException(
            "Unknown trip type or activity: " + ", ".join(sorted(set(unknown))) + "."
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
    country = home_country().code

    return AdminAreasOut(
        divisions=[
            DivisionOut(name=division, districts=district_names(country, division))
            for division in divisions(country)
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
    country = home_country()
    district = find_district(country.code, payload.district)

    if district is None:
        raise ResourceNotFoundException(f"'{payload.district}' is not a district we know.")

    return PlaceIn(
        name=payload.name,
        country_code=country.code,
        country_name=country.name,
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

    gadget = Gadget(
        **payload.model_dump(),
        slug=await unique_gadget_slug(db, payload.name),
        created_by_id=user.id,
        updated_by_id=user.id,
    )
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

    if "name" in changes:
        # Keep the public URL in step with the name.
        gadget.slug = await unique_gadget_slug(db, changes["name"], except_id=gadget.id)

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
        await _discard_image_set(get_image_storage(), image_key)


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
    renditions = await asyncio.to_thread(process_image, data)

    storage = get_image_storage()
    new_key = new_image_key()
    old_key = gadget.image_key

    await _store_image_set(storage, new_key, renditions)

    gadget.image_key = new_key
    gadget.updated_by_id = user.id

    try:
        await db.commit()
    except Exception:
        await _discard_image_set(storage, new_key)
        raise

    if old_key:
        await _discard_image_set(storage, old_key)

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
        await _discard_image_set(get_image_storage(), old_key)

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
    await _check_taxonomy(db, payload.trip_types, payload.activities)
    place = await _upsert_place(db, payload.place)

    db.add(
        Placement(
            gadget_id=gadget_id,
            place_id=place.id,
            trip_types=payload.trip_types,
            activities=payload.activities,
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
    await _check_taxonomy(db, payload.trip_types, payload.activities)

    if payload.place is not None:
        placement.place_id = (await _upsert_place(db, payload.place)).id

    if payload.trip_types is not None:
        placement.trip_types = payload.trip_types

    if "activities" in changes:
        placement.activities = payload.activities or []

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
