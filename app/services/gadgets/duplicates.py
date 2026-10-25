"""Finding and merging gadgets that are the same item under different names.

similarity.py scores names; this applies it to the catalog:
- possible_duplicates: every pair scoring POSSIBLE or more, minus pairs a
  coordinator has confirmed are different and pairs involving rejected
  suggestions (they are retired anyway);
- similar_to: the same, for one gadget (shown when reviewing a suggestion);
- merge_into: fold one gadget into another.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import DistinctGadgetPair, Gadget
from app.exceptions.exceptions import InvalidInputException
from app.services.gadgets.similarity import POSSIBLE, similarity


@dataclass(frozen=True)
class Pair:
    a: Gadget
    b: Gadget
    score: float


async def _catalog(db) -> list[Gadget]:
    return list(
        (
            await db.scalars(
                select(Gadget)
                .options(selectinload(Gadget.placements))
                .where((Gadget.review_status.is_(None)) | (Gadget.review_status != "rejected"))
                .order_by(Gadget.name)
            )
        ).all()
    )


async def _distinct_pairs(db) -> set[tuple[int, int]]:
    rows = await db.execute(select(DistinctGadgetPair.low_id, DistinctGadgetPair.high_id))
    return {(low, high) for low, high in rows.all()}


def _key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


async def possible_duplicates(db) -> list[Pair]:
    gadgets = await _catalog(db)
    distinct = await _distinct_pairs(db)
    pairs: list[Pair] = []

    for i, a in enumerate(gadgets):
        for b in gadgets[i + 1:]:
            if _key(a.id, b.id) in distinct:
                continue
            score = similarity(a.name, b.name)
            if score >= POSSIBLE:
                pairs.append(Pair(a, b, score))

    return sorted(pairs, key=lambda p: (-p.score, p.a.name))


async def similar_to(db, gadget: Gadget) -> list[tuple[Gadget, float]]:
    distinct = await _distinct_pairs(db)
    matches = [
        (other, similarity(gadget.name, other.name))
        for other in await _catalog(db)
        if other.id != gadget.id and _key(gadget.id, other.id) not in distinct
    ]
    return sorted(
        [(g, s) for g, s in matches if s >= POSSIBLE],
        key=lambda gs: -gs[1],
    )


async def mark_distinct(db, a_id: int, b_id: int, user_id: int | None) -> None:
    if a_id == b_id:
        raise InvalidInputException("Choose two different gadgets.")
    low, high = _key(a_id, b_id)
    if await db.get(DistinctGadgetPair, (low, high)) is None:
        db.add(DistinctGadgetPair(low_id=low, high_id=high, decided_by_id=user_id))


_FILLABLE = ("description", "category", "brand", "model_name", "color")


def merge_into(source: Gadget, target: Gadget) -> str | None:
    """Fold `source` into `target` and mark `source` for deletion.

    The target keeps its own name and details; gaps are filled from the
    source. Destinations move across unless the target already covers that
    place; buying options all move; suggestion counts add up; the result is
    live if either was. Returns an image key the caller should delete once
    the change is committed (the source's photo, when the target kept its
    own), or None.
    """
    if source.id == target.id:
        raise InvalidInputException("A gadget cannot be merged into itself.")

    covered = {p.place_id for p in target.placements}
    for placement in list(source.placements):
        if placement.place_id in covered:
            continue  # the target already has a reason for this place
        source.placements.remove(placement)
        target.placements.append(placement)
        covered.add(placement.place_id)

    for variant in list(source.variants):
        source.variants.remove(variant)
        target.variants.append(variant)

    for field in _FILLABLE:
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))

    leftover_image = source.image_key
    if not target.image_key and source.image_key:
        target.image_key, leftover_image = source.image_key, None
    source.image_key = None

    target.suggestion_count += source.suggestion_count

    if source.is_active and not target.is_active:
        target.is_active = True
        if target.review_status == "pending":
            target.review_status = "approved"

    return leftover_image
