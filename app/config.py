import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class EnvMetaInfo:
    llm_api_key: str | None
    llm_model: str | None
    llm_provider: str | None
    home_country: str


def get_env_meta_info() -> EnvMetaInfo:
    load_dotenv()

    return EnvMetaInfo(
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_model=os.getenv("LLM_MODEL"),
        llm_provider=os.getenv("LLM_PROVIDER"),
        # Surfaced first in destination search. Bangladesh for now;
        # change it per market without touching code.
        home_country=os.getenv("HOME_COUNTRY", "BD"),
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
