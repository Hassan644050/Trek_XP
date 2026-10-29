"""The admin-managed lists: divisions, trip types and activities.

These used to be hardcoded enums. They now live in the database so the
admin panel can edit them, and this module is the single place that reads
and writes them, keeps a slug canonical, and validates input against the
active set.
"""

import re

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.models import ActivityOption, Division, TripTypeOption


OPTION_MODELS = {"trip_type": TripTypeOption, "activity": ActivityOption}

# The original values, used only as a fallback for the public form when the
# database is unreachable -- the taxonomy tables are seeded with these, so a
# healthy app always reads the live set instead.
SEED_TRIP_TYPES = [
    ("hiking", "Hiking"), ("business", "Business"), ("beach", "Beach"),
    ("city", "City"), ("backpacking", "Backpacking"), ("winter_sports", "Winter sports"),
]
SEED_ACTIVITIES = [
    ("photography", "Photography"), ("diving", "Diving"), ("camping", "Camping"),
    ("cycling", "Cycling"), ("climbing", "Climbing"), ("remote_work", "Remote work"),
    # Added by migration 0013.
    ("swimming", "Swimming"), ("snorkelling", "Snorkelling"), ("surfing", "Surfing"),
    ("kayaking", "Kayaking"), ("boat_trips", "Boat trips"), ("fishing", "Fishing"),
    ("paragliding", "Paragliding"), ("wildlife_watching", "Wildlife watching"),
    ("birdwatching", "Birdwatching"), ("stargazing", "Stargazing"),
    ("tea_garden_tours", "Tea garden tours"), ("heritage_sites", "Heritage sites"),
    ("motorbike_touring", "Motorbike touring"), ("drone_flying", "Drone flying"),
    ("vlogging", "Vlogging"), ("running", "Running"),
]


def slugify(label: str) -> str:
    """A stable key for a label: "Winter Sports" -> "winter_sports"."""
    slug = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")

    return slug[:30]


# ---------- reading ----------


async def list_options(db, model, *, active_only: bool) -> list:
    query = select(model).order_by(model.sort_order, model.value)

    if active_only:
        query = query.where(model.is_active.is_(True))

    return list((await db.scalars(query)).all())


async def active_values(db, model) -> set[str]:
    rows = await db.scalars(
        select(model.value).where(model.is_active.is_(True))
    )

    return set(rows.all())


async def list_divisions(db, country_code: str) -> list[Division]:
    return list(
        (
            await db.scalars(
                select(Division)
                .where(Division.country_code == country_code.upper())
                .order_by(Division.sort_order, Division.name)
            )
        ).all()
    )


# ---------- writing ----------


async def add_option(db, model, label: str):
    """Create an option from a label, or return the existing one.

    Idempotent on the slug so adding "Beach" twice does not fail; a value
    that exists is reactivated rather than duplicated.
    """
    value = slugify(label)

    if not value:
        return None

    highest = await db.scalar(select(model.sort_order).order_by(model.sort_order.desc()).limit(1))
    next_order = (highest or 0) + 1

    stmt = (
        insert(model)
        .values(value=value, label=label.strip(), is_active=True, sort_order=next_order)
        .on_conflict_do_update(
            index_elements=[model.value],
            set_={"is_active": True, "label": label.strip()},
        )
        .returning(model)
    )

    return (await db.scalars(stmt)).one()


async def add_division(db, country_code: str, name: str) -> Division | None:
    name = " ".join(name.split())

    if not name:
        return None

    highest = await db.scalar(
        select(Division.sort_order)
        .where(Division.country_code == country_code.upper())
        .order_by(Division.sort_order.desc())
        .limit(1)
    )

    stmt = (
        insert(Division)
        .values(country_code=country_code.upper(), name=name, sort_order=(highest or 0) + 1)
        .on_conflict_do_nothing(constraint="uq_divisions_country_name")
        .returning(Division)
    )
    created = (await db.scalars(stmt)).one_or_none()

    if created is not None:
        return created

    # Already there: return the existing row.
    return await db.scalar(
        select(Division).where(
            Division.country_code == country_code.upper(), Division.name == name
        )
    )
