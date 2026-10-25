import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from app.exceptions.exceptions import InvalidImageException
from app.services.media.variants import VARIANTS, Variant


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
# Hero photos are full-width landscapes straight off a camera or phone,
# which routinely exceed the gadget limit.
HERO_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}

# Refuse anything that would decode to more than ~40 megapixels. A tiny
# file can declare enormous dimensions and exhaust memory when decoded.
MAX_PIXELS = 40_000_000


def _encode(image: Image.Image, variant: Variant) -> bytes:
    """One rendition. thumbnail() never enlarges, so an upload smaller
    than the target simply stays its own size."""
    sized = image.copy()
    sized.thumbnail((variant.max_side, variant.max_side))

    out = io.BytesIO()
    sized.save(out, "WEBP", quality=variant.quality, method=4)

    return out.getvalue()


def process_image(
    data: bytes,
    variants: tuple[Variant, ...] = VARIANTS,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> dict[str, bytes]:
    """Validate an upload and re-encode it as one WebP per rendition.

    Returns {variant name: encoded bytes} for every one of `variants` --
    the gadget renditions by default, HERO_VARIANTS for a hero photo.

    Re-encoding rather than storing the original is the security step: the
    output contains only pixels, so EXIF (including phone GPS location) and
    anything smuggled after the image data are gone. The format is detected
    from the bytes themselves; file names and declared content types are
    not trusted.

    Serving one 1200px file into a 44px listing row wasted most of the
    bytes a coordinator uploaded, so the sizes the pages actually display
    are produced here instead -- see variants.py.
    """
    if not data:
        raise InvalidImageException("The uploaded file is empty.")

    if len(data) > max_bytes:
        raise InvalidImageException(f"Images must be {max_bytes // (1024 * 1024)} MB or smaller.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)

            with Image.open(io.BytesIO(data)) as probe:
                if probe.format not in ACCEPTED_FORMATS:
                    raise InvalidImageException("Upload a JPEG, PNG or WebP image.")

                width, height = probe.size

                if width * height > MAX_PIXELS:
                    raise InvalidImageException("That image's dimensions are too large.")

                # verify() checks the file's structure without decoding it,
                # and leaves the image unusable, hence the second open.
                probe.verify()

            with Image.open(io.BytesIO(data)) as image:
                # Honour the camera's rotation flag before discarding EXIF,
                # or portrait phone photos come out sideways.
                image = ImageOps.exif_transpose(image)

                has_alpha = image.mode in ("RGBA", "LA") or (
                    image.mode == "P" and "transparency" in image.info
                )
                image = image.convert("RGBA" if has_alpha else "RGB")

                # Bound it once up front, then derive the smaller
                # renditions from that copy rather than from the original.
                # Downscaling a 40 megapixel photo three times over is
                # wasted work, and 480px off 1200px is indistinguishable
                # from 480px off the original.
                largest = max(variant.max_side for variant in variants)
                image.thumbnail((largest, largest))

                return {
                    variant.name: _encode(image, variant)
                    for variant in variants
                }

    except InvalidImageException:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidImageException("Upload a JPEG, PNG or WebP image.")
    except (OSError, ValueError, SyntaxError):
        # Truncated or corrupt files surface as these from Pillow.
        raise InvalidImageException("That image file is damaged or incomplete.")
