import os
from dataclasses import dataclass

from dotenv import load_dotenv


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
