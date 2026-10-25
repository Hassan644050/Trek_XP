"""The renditions every gadget upload produces.

One registry, imported by both the processing step (which needs the
dimensions) and the storage step (which needs the names to build and clean
up keys), so the two can never disagree about what exists.

Sizes are driven by what the pages actually display, at up to 3x device
pixel ratio -- the sizes are in the comments beside each one, and
`tests/test_images.py` asserts they still cover the CSS.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Variant:
    name: str
    # Longest side in pixels. Aspect ratio is preserved and images are
    # never enlarged, so a small upload stays small in every rendition.
    max_side: int
    quality: int


# Listing rows show a 44px square (object-fit: cover). 44 x 3 = 132.
THUMB = Variant("thumb", 144, 80)

# The editor preview is a 140px square. 140 x 3 = 420.
DETAIL = Variant("detail", 480, 82)

# Not displayed anywhere yet. Kept because it is the only copy of the
# original pixels we keep, so larger renditions -- a traveller-facing card,
# a lightbox -- can be derived later without asking coordinators to upload
# again. A measured upload was 9.8 KB, so this costs almost nothing.
FULL = Variant("full", 1200, 82)

VARIANTS = (THUMB, DETAIL, FULL)

VARIANT_NAMES = tuple(variant.name for variant in VARIANTS)


# ---------- home page hero photos ----------
#
# The hero spans the page width and crops with object-fit: cover, so its
# renditions are wide. Phones get HERO_SMALL (a ~343px-wide hero at 3x);
# desktops get HERO_FULL (a ~1900px hero at about 1.25x). The large one is
# named "full" so it takes the plain, unsuffixed key, like a gadget's FULL.
HERO_SMALL = Variant("small", 1080, 78)
HERO_FULL = Variant("full", 2400, 78)

HERO_VARIANTS = (HERO_SMALL, HERO_FULL)

HERO_VARIANT_NAMES = tuple(variant.name for variant in HERO_VARIANTS)

BY_NAME = {variant.name: variant for variant in VARIANTS}
