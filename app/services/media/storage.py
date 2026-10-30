import re
import uuid
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from app.config import get_media_settings, get_r2_settings
from app.services.media.variants import FULL, VARIANT_NAMES


# Keys are generated here, never taken from users, so this pattern doubles
# as a guard against path traversal if a key is ever read back from input.
_KEY_PATTERN = re.compile(r"^(gadgets|heroes)/[0-9a-f]{32}(_[a-z]{3,10})?\.webp$")

KEY_FOLDERS = ("gadgets", "heroes")


def new_image_key(folder: str = "gadgets") -> str:
    # A fresh random key per upload: replacing an image changes its URL,
    # so browsers and CDNs never show a stale cached copy.
    if folder not in KEY_FOLDERS:
        raise ValueError(f"unknown image folder {folder!r}")

    return f"{folder}/{uuid.uuid4().hex}.webp"


def is_valid_key(key: str) -> bool:
    return bool(_KEY_PATTERN.match(key))


def variant_key(key: str, variant: str) -> str:
    """The key a given rendition of `key` is stored under.

    The full rendition keeps the plain, unsuffixed key. That asymmetry is
    deliberate: it is the value the database holds, so it always names an
    object that exists, and rows written before renditions existed stay
    valid. The smaller renditions hang off it by suffix.
    """
    if variant == FULL.name:
        return key

    return f"{key.removesuffix('.webp')}_{variant}.webp"


def all_keys(key: str, names: tuple[str, ...] = VARIANT_NAMES) -> list[str]:
    """Every rendition of one upload -- what deleting it has to remove.
    Pass HERO_VARIANT_NAMES for a hero photo."""
    return [variant_key(key, name) for name in names]


class ImageStorage(ABC):
    """Where processed gadget images live.

    Local disk for development; Cloudflare R2 in production, because free
    hosting tiers wipe their disks on every deploy. See R2ImageStorage.

    Implementations block on I/O, so callers in async code run them on a
    worker thread -- a put to R2 would otherwise stall the event loop.
    """

    @abstractmethod
    def save(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def read(self, key: str) -> bytes | None:
        """The stored bytes, or None if the key holds nothing.

        The full rendition is read back to derive the smaller ones from it
        (which is what keeping a full copy is for), and thumbnails to draw
        the share card (routes/home.py).
        """

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def url(self, key: str) -> str: ...


class LocalImageStorage(ImageStorage):
    def __init__(self, directory: Path, url_prefix: str):
        self.directory = directory
        self.url_prefix = url_prefix.rstrip("/")

    def _path(self, key: str) -> Path:
        if not is_valid_key(key):
            raise ValueError(f"Refusing unexpected image key: {key!r}")

        return self.directory / key

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a reader never sees a half-written file.
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def read(self, key: str) -> bytes | None:
        path = self._path(key)

        return path.read_bytes() if path.exists() else None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def url(self, key: str) -> str:
        return f"{self.url_prefix}/{key}"


@lru_cache(maxsize=1)
def get_image_storage() -> ImageStorage:
    """R2 when it is configured, local disk otherwise.

    Cached because building the R2 client is slow enough to notice, and the
    client is safe to share across requests and worker threads.
    """
    r2 = get_r2_settings()

    if r2 is not None:
        # Imported here so botocore is only loaded when it is needed.
        from app.services.media.r2 import R2ImageStorage

        return R2ImageStorage(r2)

    settings = get_media_settings()

    return LocalImageStorage(settings.directory, settings.url_prefix)
