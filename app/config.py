import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from app.exceptions.exceptions import ImageStorageNotConfiguredException


PROJECT_ROOT = Path(__file__).resolve().parents[1]


# Measured: a real Gemini call for a fresh destination took 52s, so a tight
# bound would fail legitimate requests. These cap the two ways a stalled
# upstream used to hang forever -- one HTTP attempt, and the whole call
# including retries.
LLM_TIMEOUT_SECONDS = 75
LLM_TOTAL_TIMEOUT_SECONDS = 100


@dataclass
class EnvMetaInfo:
    llm_api_key: str | None
    llm_model: str | None
    llm_provider: str | None
    home_country: str
    llm_timeout_seconds: int
    llm_total_timeout_seconds: int


def get_env_meta_info() -> EnvMetaInfo:
    load_dotenv()

    return EnvMetaInfo(
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_model=os.getenv("LLM_MODEL"),
        llm_provider=os.getenv("LLM_PROVIDER"),
        # Surfaced first in destination search. Bangladesh for now;
        # change it per market without touching code.
        home_country=os.getenv("HOME_COUNTRY", "BD"),
        llm_timeout_seconds=int(
            os.getenv("LLM_TIMEOUT_SECONDS", str(LLM_TIMEOUT_SECONDS))
        ),
        llm_total_timeout_seconds=int(
            os.getenv("LLM_TOTAL_TIMEOUT_SECONDS", str(LLM_TOTAL_TIMEOUT_SECONDS))
        ),
    )


@dataclass
class DatabaseSettings:
    url: str | None


def get_database_settings() -> DatabaseSettings:
    load_dotenv()

    return DatabaseSettings(url=os.getenv("DATABASE_URL"))


@dataclass
class AuthSettings:
    session_hours: int
    # Secure cookies are only sent over HTTPS. Required in production;
    # switched off locally because the dev server is plain http.
    cookie_secure: bool
    max_failed_logins: int
    lockout_minutes: int


def get_auth_settings() -> AuthSettings:
    load_dotenv()

    return AuthSettings(
        session_hours=int(os.getenv("SESSION_HOURS", "12")),
        cookie_secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        max_failed_logins=int(os.getenv("MAX_FAILED_LOGINS", "5")),
        lockout_minutes=int(os.getenv("LOCKOUT_MINUTES", "15")),
    )


@dataclass
class MediaSettings:
    directory: Path
    url_prefix: str


def get_media_settings() -> MediaSettings:
    load_dotenv()

    return MediaSettings(
        directory=Path(os.getenv("MEDIA_DIR", str(PROJECT_ROOT / "media"))),
        url_prefix="/media",
    )


# Cloudflare R2, reached over its S3-compatible API. All five are needed
# together: credentials without a public base URL would store images the app
# cannot then serve, and a base URL without credentials stores nothing.
R2_ENV_VARS = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "R2_PUBLIC_BASE_URL",
)


@dataclass
class R2Settings:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    # The bucket's public hostname -- an r2.dev address or a custom domain.
    # Uploading does not make a bucket readable; this has to be turned on
    # in the R2 console separately.
    public_base_url: str


def get_r2_settings() -> R2Settings | None:
    """R2 settings if they are configured, else None for local disk.

    Half-configured is treated as an error rather than as "not configured":
    silently writing to disk when someone meant to write to R2 loses every
    image on the next deploy.
    """
    load_dotenv()

    values = {name: (os.getenv(name) or "").strip() for name in R2_ENV_VARS}

    if not any(values.values()):
        return None

    missing = [name for name in R2_ENV_VARS if not values[name]]

    if missing:
        raise ImageStorageNotConfiguredException(
            "Cloudflare R2 is partly configured. Also set: "
            + ", ".join(missing)
        )

    return R2Settings(
        account_id=values["R2_ACCOUNT_ID"],
        access_key_id=values["R2_ACCESS_KEY_ID"],
        secret_access_key=values["R2_SECRET_ACCESS_KEY"],
        bucket=values["R2_BUCKET"],
        public_base_url=values["R2_PUBLIC_BASE_URL"],
    )
