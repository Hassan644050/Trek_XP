"""Saving and removing one upload's set of renditions.

Shared by every route that stores images (gadget images, hero photos).
Storage is blocking I/O -- a put to R2 is a network round trip -- so every
call goes to a worker thread rather than stalling the event loop.
"""

import asyncio
import logging

from app.services.media.storage import all_keys, variant_key
from app.services.media.variants import VARIANT_NAMES


logger = logging.getLogger(__name__)


async def store_image_set(storage, key: str, renditions: dict[str, bytes]) -> None:
    """Save every rendition, or leave nothing behind.

    A half-written set would show a page an image that 404s, so a failure
    part way through takes the ones already written with it before the
    error propagates.
    """
    written: list[str] = []

    try:
        for variant, data in renditions.items():
            target = variant_key(key, variant)
            await asyncio.to_thread(storage.save, target, data)
            written.append(target)
    except Exception:
        for target in written:
            await discard_image(storage, target)
        raise


async def discard_image(storage, key: str) -> None:
    """Delete one stored object we no longer want, best effort.

    Called only once the database says so. A leftover object wastes a few
    kilobytes; failing the request would report an error for work that has
    already succeeded, or hide the error that triggered the cleanup.
    """
    try:
        await asyncio.to_thread(storage.delete, key)
    except Exception:
        logger.warning("Could not delete image %s", key, exc_info=True)


async def discard_image_set(storage, key: str, names: tuple[str, ...] = VARIANT_NAMES) -> None:
    """Every rendition of one upload."""
    for target in all_keys(key, names):
        await discard_image(storage, target)
