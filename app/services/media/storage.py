import re
import uuid
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from app.config import get_media_settings


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

    Local disk for development. Free hosting tiers wipe their disks on every
    deploy, so production needs an object-store implementation (S3,
    Cloudflare R2, Cloudinary) behind this same interface.
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
    settings = get_media_settings()
    return LocalImageStorage(settings.directory, settings.url_prefix)
