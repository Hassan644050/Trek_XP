import re
import uuid
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from app.config import get_media_settings, get_r2_settings


# Keys are generated here, never taken from users, so this pattern doubles
# as a guard against path traversal if a key is ever read back from input.
_KEY_PATTERN = re.compile(r"^gadgets/[0-9a-f]{32}\.webp$")


def new_image_key() -> str:
    # A fresh random key per upload: replacing an image changes its URL,
    # so browsers and CDNs never show a stale cached copy.
    return f"gadgets/{uuid.uuid4().hex}.webp"


def is_valid_key(key: str) -> bool:
    return bool(_KEY_PATTERN.match(key))


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
