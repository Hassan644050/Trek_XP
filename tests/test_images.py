import io

import pytest
from PIL import Image

from app.exceptions.exceptions import InvalidImageException
from app.services.media.images import MAX_UPLOAD_BYTES, process_image
from app.services.media.storage import (
    LocalImageStorage,
    all_keys,
    is_valid_key,
    new_image_key,
    variant_key,
)
from app.services.media.variants import DETAIL, FULL, THUMB, VARIANT_NAMES


def encode(image: Image.Image, fmt: str, **kwargs) -> bytes:
    out = io.BytesIO()
    image.save(out, fmt, **kwargs)
    return out.getvalue()


def decode(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def full(data: bytes) -> Image.Image:
    """The full rendition of an upload, decoded."""
    return decode(process_image(data)[FULL.name])


def test_jpeg_becomes_webp():
    result = full(encode(Image.new("RGB", (400, 300), "orange"), "JPEG"))
    assert result.format == "WEBP"
    assert result.size == (400, 300)


def test_large_image_is_scaled_down_keeping_proportions():
    result = full(encode(Image.new("RGB", (3000, 1500), "blue"), "PNG"))
    assert result.size == (FULL.max_side, FULL.max_side // 2)


def test_png_transparency_is_kept():
    result = full(encode(Image.new("RGBA", (50, 50), (0, 0, 0, 0)), "PNG"))
    assert result.mode == "RGBA"


def test_location_metadata_is_stripped():
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (23.0, 45.0, 0.0)}  # GPSInfo: where the photo was taken
    exif[0x010F] = "PhoneMaker"  # camera make

    jpeg = encode(Image.new("RGB", (100, 100), "green"), "JPEG", exif=exif)
    assert decode(jpeg).getexif()  # sanity check: the input really has EXIF

    for data in process_image(jpeg).values():
        result = decode(data)
        assert not result.getexif()
        assert "exif" not in result.info


def test_camera_rotation_is_applied_before_metadata_is_dropped():
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90° clockwise to display

    jpeg = encode(Image.new("RGB", (200, 100), "red"), "JPEG", exif=exif)

    # Stored landscape, displayed portrait: the output must be portrait.
    assert full(jpeg).size == (100, 200)


def test_oversized_upload_is_rejected():
    with pytest.raises(InvalidImageException, match="5 MB"):
        process_image(b"\xff" * (MAX_UPLOAD_BYTES + 1))


def test_empty_upload_is_rejected():
    with pytest.raises(InvalidImageException, match="empty"):
        process_image(b"")


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-1.7 not an image",
        b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        encode(Image.new("RGB", (10, 10)), "GIF"),
        encode(Image.new("RGB", (10, 10)), "BMP"),
    ],
    ids=["pdf", "svg", "gif", "bmp"],
)
def test_other_file_types_are_rejected(data):
    with pytest.raises(InvalidImageException, match="JPEG, PNG or WebP"):
        process_image(data)


def test_truncated_image_is_rejected():
    data = encode(Image.new("RGB", (300, 300), "purple"), "PNG")

    with pytest.raises(InvalidImageException):
        process_image(data[: len(data) // 2])


def test_huge_declared_dimensions_are_rejected_without_decoding():
    # 9000 x 9000 = 81 megapixels, but the file itself is small.
    data = encode(Image.new("1", (9000, 9000)), "PNG")
    assert len(data) < MAX_UPLOAD_BYTES

    with pytest.raises(InvalidImageException):
        process_image(data)


def test_storage_round_trip(tmp_path):
    storage = LocalImageStorage(tmp_path, "/media/")
    key = new_image_key()

    storage.save(key, b"webp-bytes")

    assert (tmp_path / key).read_bytes() == b"webp-bytes"
    assert storage.url(key) == f"/media/{key}"

    storage.delete(key)
    assert not (tmp_path / key).exists()
    storage.delete(key)  # deleting twice is harmless


@pytest.mark.parametrize(
    "key", ["../../etc/passwd", "gadgets/../secret.webp", "gadgets/abc.webp", "/abs/path.webp"]
)
def test_storage_refuses_unexpected_keys(tmp_path, key):
    assert not is_valid_key(key)

    with pytest.raises(ValueError):
        LocalImageStorage(tmp_path, "/media").save(key, b"x")


def test_new_keys_are_unique_and_valid():
    keys = {new_image_key() for _ in range(50)}
    assert len(keys) == 50
    assert all(is_valid_key(k) for k in keys)


# ---------- renditions ----------


def photo(size=(2400, 1600)) -> bytes:
    """A gradient plus noise: detail that downscaling really loses, and
    that the encoder cannot compress away to nothing."""
    gradient = Image.linear_gradient("L").resize(size)
    noise = Image.effect_noise(size, 24)
    image = Image.merge("RGB", (gradient, noise, gradient.transpose(Image.Transpose.ROTATE_180)))

    return encode(image, "JPEG", quality=92)


def test_every_variant_is_produced():
    assert set(process_image(photo((600, 400)))) == set(VARIANT_NAMES)


def test_each_rendition_is_bounded_to_its_own_size():
    renditions = process_image(photo())

    assert decode(renditions[THUMB.name]).size == (THUMB.max_side, 96)
    assert decode(renditions[DETAIL.name]).size == (DETAIL.max_side, 320)
    assert decode(renditions[FULL.name]).size == (FULL.max_side, 800)


def test_the_listing_rendition_is_far_smaller_than_the_full_one():
    """The whole point: a 44px row must not download the 1200px file."""
    renditions = process_image(photo())

    assert len(renditions[THUMB.name]) < len(renditions[DETAIL.name])
    assert len(renditions[DETAIL.name]) < len(renditions[FULL.name])
    # Measured 543x on this source; 5x is a floor that cannot flake.
    assert len(renditions[THUMB.name]) * 5 < len(renditions[FULL.name])


def test_renditions_cover_the_sizes_the_pages_display():
    """If the CSS boxes change, these numbers have to change with them."""
    listing_box_px = 44
    detail_box_px = 140
    retina = 3

    assert THUMB.max_side >= listing_box_px * retina
    assert DETAIL.max_side >= detail_box_px * retina


def test_a_small_upload_is_never_enlarged():
    renditions = process_image(encode(Image.new("RGB", (60, 40), "teal"), "PNG"))

    for name in VARIANT_NAMES:
        assert decode(renditions[name]).size == (60, 40)


def test_variants_are_all_valid_keys():
    key = new_image_key()

    assert all(is_valid_key(k) for k in all_keys(key))
    assert len(set(all_keys(key))) == len(VARIANT_NAMES)


def test_the_full_rendition_keeps_the_plain_key():
    """It is the value stored in the database, so it must name a real
    object -- and rows written before renditions existed stay valid."""
    key = new_image_key()

    assert variant_key(key, FULL.name) == key
    assert variant_key(key, THUMB.name) == key.removesuffix(".webp") + "_thumb.webp"


def test_a_variant_key_is_not_mistaken_for_another_upload():
    a, b = new_image_key(), new_image_key()

    assert set(all_keys(a)).isdisjoint(all_keys(b))
