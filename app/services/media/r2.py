"""Cloudflare R2 image storage, over R2's S3-compatible API.

Kept in its own module so the local-disk path never imports botocore --
this is only loaded when R2 is actually configured.
"""

import logging

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import R2Settings
from app.exceptions.exceptions import ImageStorageException
from app.services.media.storage import ImageStorage, is_valid_key


logger = logging.getLogger(__name__)

# Keys are random and never reused, so an object's bytes never change and
# browsers may keep it forever. That also keeps repeat views off the free
# tier's Class B operation allowance.
CACHE_CONTROL = "public, max-age=31536000, immutable"

# Everything that reaches storage has been re-encoded by process_image.
CONTENT_TYPE = "image/webp"

# A coordinator is waiting on the upload, so fail rather than hang. Images
# are ~10 KB, so a slow request here means something is wrong.
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 3


def build_client(settings: R2Settings):
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        # R2 is a single global namespace with no regions, but SigV4 needs
        # a region in the signature; "auto" is what R2 documents.
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": MAX_ATTEMPTS, "mode": "standard"},
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            read_timeout=READ_TIMEOUT_SECONDS,
        ),
    )


class R2ImageStorage(ImageStorage):
    """Gadget images in a Cloudflare R2 bucket.

    Free hosting tiers wipe their disk on every deploy, so anything a
    coordinator uploads has to live outside the application.
    """

    def __init__(self, settings: R2Settings, client=None):
        self.bucket = settings.bucket
        self.public_base_url = settings.public_base_url.rstrip("/")
        # Injectable so tests never reach the network.
        self.client = client if client is not None else build_client(settings)

    @staticmethod
    def _checked(key: str) -> str:
        # Same guard as local disk: keys come from new_image_key(), never
        # from a request, and this keeps it that way.
        if not is_valid_key(key):
            raise ValueError(f"Refusing unexpected image key: {key!r}")

        return key

    def save(self, key: str, data: bytes) -> None:
        self._checked(key)

        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=CONTENT_TYPE,
                CacheControl=CACHE_CONTROL,
            )
        except (BotoCoreError, ClientError) as exc:
            # The bucket name and endpoint belong in the logs, not in a
            # message shown to a coordinator.
            logger.warning("R2 put_object failed for %s: %s", key, exc)

            raise ImageStorageException(
                "The image could not be stored just now."
            ) from exc

    def delete(self, key: str) -> None:
        self._checked(key)

        try:
            # S3 deletes are idempotent: a missing key is not an error,
            # which matches the local implementation's missing_ok.
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            logger.warning("R2 delete_object failed for %s: %s", key, exc)

            raise ImageStorageException(
                "The image could not be removed just now."
            ) from exc

    def url(self, key: str) -> str:
        return f"{self.public_base_url}/{key}"
