"""Home page hero photos: lookup and serialization shared by the public
read and the admin panel."""

import time

from sqlalchemy import select

from app.db.models import HeroImage
from app.models.catalog import HeroImageOut
from app.services.media.storage import get_image_storage, variant_key
from app.services.media.variants import HERO_FULL, HERO_SMALL
from app.services.slug import url_slug


def hero_slug(place_name: str | None) -> str:
    """The key a hero is stored under: the destination's URL slug, or ""
    for the country's default hero."""
    return url_slug(place_name) if place_name and place_name.strip() else ""


def hero_out(hero: HeroImage) -> HeroImageOut:
    storage = get_image_storage()

    return HeroImageOut(
        id=hero.id,
        place_slug=hero.place_slug,
        place_name=hero.place_name,
        alt=hero.alt,
        small_url=storage.url(variant_key(hero.image_key, HERO_SMALL.name)),
        image_url=storage.url(variant_key(hero.image_key, HERO_FULL.name)),
        updated_at=hero.updated_at,
    )


async def list_heroes(db, country_code: str) -> list[HeroImage]:
    # The default hero ("" slug) sorts first, then destinations by name.
    return list(
        (
            await db.scalars(
                select(HeroImage)
                .where(HeroImage.country_code == country_code)
                .order_by(HeroImage.place_slug != "", HeroImage.place_name)
            )
        ).all()
    )


# ---------- public read cache ----------
#
# Every home page view asks for the hero list, and each lookup is a fresh
# connection to Neon (pooler, NullPool) -- measured at ~2.7s, which made the
# photo pop in seconds after the page. Photos change rarely, so the public
# list is cached per country and dropped whenever an admin changes one.
# With several workers, a worker that did not handle the upload catches up
# within the TTL.

HERO_CACHE_SECONDS = 300

_cache: dict[str, tuple[float, list[HeroImageOut]]] = {}


def cached_heroes(country_code: str) -> list[HeroImageOut] | None:
    hit = _cache.get(country_code)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    return None


def remember_heroes(country_code: str, heroes: list[HeroImageOut]) -> None:
    _cache[country_code] = (time.monotonic() + HERO_CACHE_SECONDS, heroes)


def forget_heroes() -> None:
    _cache.clear()
