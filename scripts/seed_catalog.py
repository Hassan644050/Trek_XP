"""Load the generic travel-product dataset into the catalog.

    python -m scripts.seed_catalog [--dry-run]

Reads app/data/catalog_seed.json -- products organized by destination --
and creates the places, gadgets and placements a traveller sees as
community-verified items.

Safe to re-run: a place is matched by name and coordinates, a gadget by
its name, and a placement by its gadget-and-place pair, so nothing is
duplicated. New destinations or products added to the dataset are picked
up; existing rows are left as they are.

Everything existing is read in three queries up front and the rest is
diffed in memory, so the run is a few round trips rather than one per row
-- which matters over a remote database.
"""

import asyncio
import json
import sys

from sqlalchemy import func, select

from app.config import PROJECT_ROOT
from app.db.engine import get_engine, get_sessionmaker
from app.db.models import Gadget, Place, Placement, Role, User
from app.models.recommendation import Priority


SEED_PATH = PROJECT_ROOT / "app" / "data" / "catalog_seed.json"


# A place already in the catalog under the same name this close is treated
# as the same spot and reused, so a slightly different coordinate from an
# earlier entry does not create a duplicate. ~0.05 degrees is about 5.5 km.
_SAME_PLACE_DEGREES = 0.05


def _find_place(existing: list, name: str, lat: float, lon: float):
    """An existing place with this name close to this point, or None."""
    for place in existing:
        if (
            place.name.lower() == name.lower()
            and abs(place.latitude - lat) <= _SAME_PLACE_DEGREES
            and abs(place.longitude - lon) <= _SAME_PLACE_DEGREES
        ):
            return place

    return None


async def main() -> int:
    dry_run = "--dry-run" in sys.argv
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    async with get_sessionmaker()() as db:
        author = await db.scalar(select(User.id).where(User.role == Role.ADMIN).limit(1))

        # Read the whole catalog up front: three queries, not one per row.
        existing_places = (await db.scalars(select(Place))).all()
        gadgets = {
            name.lower(): gid
            for name, gid in (await db.execute(select(Gadget.name, Gadget.id))).all()
        }
        existing_placements = {
            tuple(row)
            for row in (await db.execute(select(Placement.gadget_id, Placement.place_id))).all()
        }

        # 1. Create any missing places and gadgets, then flush to get ids.
        #    place_for maps each dataset destination to its Place (reused or new).
        new_places = new_gadgets = 0
        place_for: dict[int, object] = {}

        for i, dest in enumerate(data["destinations"]):
            place = _find_place(existing_places, dest["name"], dest["latitude"], dest["longitude"])
            if place is None:
                place = Place(
                    name=dest["name"], country_code=dest["country_code"],
                    country_name=dest["country_name"], latitude=dest["latitude"],
                    longitude=dest["longitude"], division=dest.get("division"),
                )
                db.add(place)
                existing_places.append(place)
                new_places += 1
            place_for[i] = place

            for product in dest["products"]:
                name = product["name"]
                if name.lower() not in gadgets:
                    db.add(gadget := Gadget(
                        name=name, category=product["category"],
                        created_by_id=author, updated_by_id=author,
                    ))
                    gadgets[name.lower()] = gadget
                    new_gadgets += 1

        await db.flush()  # assigns ids to the new Place/Gadget objects

        def gadget_id_of(key):
            value = gadgets[key]
            return value if isinstance(value, int) else value.id

        # 2. Create any missing placements.
        new_placements = skipped = 0

        for i, dest in enumerate(data["destinations"]):
            place_id = place_for[i].id

            for product in dest["products"]:
                gadget_id = gadget_id_of(product["name"].lower())

                if (gadget_id, place_id) in existing_placements:
                    skipped += 1
                    continue

                existing_placements.add((gadget_id, place_id))
                db.add(Placement(
                    gadget_id=gadget_id, place_id=place_id,
                    trip_types=product["trip_types"], activities=product["activities"],
                    priority=Priority(product["priority"]), why=product["why"],
                    created_by_id=author, updated_by_id=author,
                ))
                new_placements += 1

        if dry_run:
            await db.rollback()
            print("[dry run] nothing written.")
        else:
            await db.commit()

    await get_engine().dispose()

    verb = "would add" if dry_run else "added"
    print(
        f"{verb}: {new_places} place(s), {new_gadgets} gadget(s), "
        f"{new_placements} placement(s); {skipped} placement(s) already present, "
        f"across {len(data['destinations'])} destination(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
