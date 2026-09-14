import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class EnvMetaInfo:
    llm_api_key: str | None
    llm_model: str | None
    llm_provider: str | None


def get_env_meta_info() -> EnvMetaInfo:
    load_dotenv()

    return EnvMetaInfo(
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_model=os.getenv("LLM_MODEL"),
        llm_provider=os.getenv("LLM_PROVIDER"),
    )
