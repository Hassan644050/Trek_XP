import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from app.exceptions.exceptions import InvalidImageException


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}

# Gadget cards are small; 1200px covers high-density screens.
MAX_SIDE_PX = 1200
WEBP_QUALITY = 82

# Refuse anything that would decode to more than ~40 megapixels. A tiny
# file can declare enormous dimensions and exhaust memory when decoded.
MAX_PIXELS = 40_000_000


def process_image(data: bytes) -> bytes:
    """Validate an upload and re-encode it as a bounded WebP.

    Re-encoding rather than storing the original is the security step: the
    output contains only pixels, so EXIF (including phone GPS location) and
    anything smuggled after the image data are gone. The format is detected
    from the bytes themselves; file names and declared content types are
    not trusted.
    """
    if not data:
        raise InvalidImageException("The uploaded file is empty.")

    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidImageException("Images must be 5 MB or smaller.")

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
                image.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))

                has_alpha = image.mode in ("RGBA", "LA") or (
                    image.mode == "P" and "transparency" in image.info
                )
                image = image.convert("RGBA" if has_alpha else "RGB")

                out = io.BytesIO()
                image.save(out, "WEBP", quality=WEBP_QUALITY, method=4)
                return out.getvalue()

    except InvalidImageException:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidImageException("Upload a JPEG, PNG or WebP image.")
    except (OSError, ValueError, SyntaxError):
        # Truncated or corrupt files surface as these from Pillow.
        raise InvalidImageException("That image file is damaged or incomplete.")
