import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.config import R2_ENV_VARS, R2Settings, get_r2_settings
from app.exceptions.exceptions import (
    ImageStorageException,
    ImageStorageNotConfiguredException,
)
from app.services.media.r2 import R2ImageStorage, build_client
from app.services.media.storage import (
    LocalImageStorage,
    get_image_storage,
    new_image_key,
)


SETTINGS = R2Settings(
    account_id="acct123",
    access_key_id="key-id",
    secret_access_key="secret",
    bucket="trekxp-images",
    public_base_url="https://images.example.com",
)


class FakeS3:
    """Records calls instead of reaching Cloudflare."""

    def __init__(self, error=None):
        self.error = error
        self.puts = []
        self.deletes = []

    def put_object(self, **kwargs):
        if self.error is not None:
            raise self.error
        self.puts.append(kwargs)

    def delete_object(self, **kwargs):
        if self.error is not None:
            raise self.error
        self.deletes.append(kwargs)


def storage(client=None, settings=SETTINGS):
    return R2ImageStorage(settings, client=client or FakeS3())


@pytest.fixture
def no_dotenv(monkeypatch):
    """Read only the environment the test sets, never the developer's .env."""
    monkeypatch.setattr("app.config.load_dotenv", lambda *a, **k: False)

    for name in R2_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ---------- settings ----------


def test_no_r2_variables_means_not_configured(no_dotenv):
    assert get_r2_settings() is None


def test_all_five_variables_are_read(no_dotenv, monkeypatch):
    for name, value in zip(R2_ENV_VARS, ["a", "b", "c", "d", "https://e.example"]):
        monkeypatch.setenv(name, value)

    assert get_r2_settings() == R2Settings(
        account_id="a",
        access_key_id="b",
        secret_access_key="c",
        bucket="d",
        public_base_url="https://e.example",
    )


def test_half_configured_r2_is_an_error_not_a_fallback(no_dotenv, monkeypatch):
    """Falling back to disk here loses every image on the next deploy."""
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("R2_BUCKET", "trekxp-images")

    with pytest.raises(ImageStorageNotConfiguredException) as caught:
        get_r2_settings()

    message = str(caught.value)
    # Names what is missing, so the fix does not need guesswork.
    assert "R2_ACCESS_KEY_ID" in message
    assert "R2_SECRET_ACCESS_KEY" in message
    assert "R2_PUBLIC_BASE_URL" in message
    assert "R2_BUCKET" not in message


def test_blank_variables_count_as_unset(no_dotenv, monkeypatch):
    """A commented-out value left as "" must not read as configured."""
    for name in R2_ENV_VARS:
        monkeypatch.setenv(name, "   ")

    assert get_r2_settings() is None


# ---------- the storage implementation ----------


def test_save_uploads_to_the_bucket_as_a_cacheable_webp():
    client = FakeS3()
    key = new_image_key()

    storage(client).save(key, b"webp-bytes")

    assert client.puts == [
        {
            "Bucket": "trekxp-images",
            "Key": key,
            "Body": b"webp-bytes",
            "ContentType": "image/webp",
            # Keys are never reused, so the object may be cached forever.
            "CacheControl": "public, max-age=31536000, immutable",
        }
    ]


def test_delete_removes_the_object():
    client = FakeS3()
    key = new_image_key()

    storage(client).delete(key)

    assert client.deletes == [{"Bucket": "trekxp-images", "Key": key}]


def test_url_is_built_from_the_public_base():
    key = new_image_key()

    assert storage().url(key) == f"https://images.example.com/{key}"


def test_a_trailing_slash_on_the_base_does_not_double_up():
    trailing = R2Settings(**{**SETTINGS.__dict__, "public_base_url": "https://img.example.com/"})
    key = new_image_key()

    assert R2ImageStorage(trailing, client=FakeS3()).url(key) == f"https://img.example.com/{key}"


@pytest.mark.parametrize("key", ["../secrets.webp", "gadgets/x.webp", "gadgets/abc.png", ""])
def test_unexpected_keys_never_reach_the_bucket(key):
    client = FakeS3()

    with pytest.raises(ValueError):
        storage(client).save(key, b"x")

    with pytest.raises(ValueError):
        storage(client).delete(key)

    assert client.puts == [] and client.deletes == []


@pytest.mark.parametrize(
    "error",
    [
        ClientError({"Error": {"Code": "NoSuchBucket", "Message": "gone"}}, "PutObject"),
        EndpointConnectionError(endpoint_url="https://acct123.r2.cloudflarestorage.com"),
    ],
)
def test_upload_failures_become_a_storage_error(error):
    with pytest.raises(ImageStorageException) as caught:
        storage(FakeS3(error=error)).save(new_image_key(), b"x")

    # Bucket names and endpoints belong in the logs, not in the response.
    message = str(caught.value)
    assert "trekxp-images" not in message
    assert "cloudflarestorage" not in message


def test_delete_failures_become_a_storage_error():
    error = ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "DeleteObject")

    with pytest.raises(ImageStorageException):
        storage(FakeS3(error=error)).delete(new_image_key())


# ---------- the client and the factory ----------


def test_client_points_at_the_account_endpoint():
    client = build_client(SETTINGS)

    assert client.meta.endpoint_url == "https://acct123.r2.cloudflarestorage.com"
    # R2 has no regions, but SigV4 still needs one in the signature.
    assert client.meta.region_name == "auto"


def test_factory_uses_r2_when_it_is_configured(no_dotenv, monkeypatch):
    for name, value in zip(R2_ENV_VARS, ["a", "b", "c", "d", "https://e.example"]):
        monkeypatch.setenv(name, value)
    get_image_storage.cache_clear()

    try:
        assert isinstance(get_image_storage(), R2ImageStorage)
    finally:
        get_image_storage.cache_clear()


def test_factory_falls_back_to_local_disk(no_dotenv):
    get_image_storage.cache_clear()

    try:
        assert isinstance(get_image_storage(), LocalImageStorage)
    finally:
        get_image_storage.cache_clear()
