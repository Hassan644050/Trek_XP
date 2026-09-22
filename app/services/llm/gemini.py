from google import genai
from google.genai import errors as genai_errors
from app.config import get_env_meta_info
from app.services.llm.base import LLMProvider
from app.services.llm.retry import retry_on_transient
from app.exceptions.exceptions import (
    LLMException,
    LLMRateLimitException,
    LLMProviderException,
)

class GeminiProvider(LLMProvider):
    def __init__(self):
        env_meta_info = get_env_meta_info()
        self.client = genai.Client(
            api_key=env_meta_info.llm_api_key
        )
        self.model = env_meta_info.llm_model

    @retry_on_transient(genai_errors.ServerError)
    def _call(self, prompt: str):
        return self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )

    def generate(self, prompt: str) -> str:
        try:

            response = self._call(prompt)
            text = response.text

            if not text:
                raise LLMProviderException(
                    "The model returned an empty response."
                )

            return text

        except LLMException:
            # Already one of ours (e.g. the empty-response guard) --
            # do not relabel it with a generic message.
            raise

        except Exception as exc:

            error_message = str(exc)

            if "429" in error_message or "RateLimit" in error_message:
                raise LLMRateLimitException(
                    "LLM rate limit exceeded."
                ) from exc

            raise LLMProviderException(
                "LLM provider request failed."
            ) from exc

