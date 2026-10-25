"""Home page hero photos: lookup and serialization shared by the public
read and the admin panel."""

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

