"""Derive the missing thumbnail and detail renditions for existing gadgets.

    python -m scripts.backfill_renditions [--dry-run]

Images uploaded before renditions existed are stored as a single file. The
listing asks for a `_thumb` copy that was never written, so those gadgets
show a broken image.

Each one is rebuilt from the stored full copy, which is exactly what
keeping that copy is for. The full rendition itself is never rewritten:
re-encoding it would lose quality for no reason.

Safe to run more than once -- it only writes renditions that are missing.
"""

import asyncio
import sys

from sqlalchemy import select

from app.db.engine import get_engine, get_sessionmaker
from app.db.models import Gadget
from app.services.media.images import process_image
from app.services.media.storage import get_image_storage, variant_key
from app.services.media.variants import FULL, VARIANTS


async def main() -> int:
    dry_run = "--dry-run" in sys.argv
    storage = get_image_storage()
    rebuilt = missing_source = 0

    async with get_sessionmaker()() as db:
        gadgets = (
            await db.scalars(select(Gadget).where(Gadget.image_key.is_not(None)))
        ).all()

        print(f"{len(gadgets)} gadget(s) with an image.")

        for gadget in gadgets:
            key = gadget.image_key
            wanted = [
                variant_key(key, v.name) for v in VARIANTS if v.name != FULL.name
            ]
            absent = [k for k in wanted if storage.read(k) is None]

            if not absent:
                continue

            original = storage.read(variant_key(key, FULL.name))

            if original is None:
                # The row points at bytes that are gone; only a re-upload
                # can fix that, so say so rather than failing silently.
                print(f"  !! {gadget.name}: full copy missing at {key}")
                missing_source += 1
                continue

            print(f"  -> {gadget.name}: {len(absent)} rendition(s) missing")

            if dry_run:
                rebuilt += 1
                continue

            renditions = process_image(original)

            for target in absent:
                variant = target.removesuffix(".webp").rsplit("_", 1)[-1]
                storage.save(target, renditions[variant])

            rebuilt += 1

    await get_engine().dispose()

    verb = "would rebuild" if dry_run else "rebuilt"
    print(f"{verb} {rebuilt} gadget(s); {missing_source} with no source image.")

    return 1 if missing_source else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
