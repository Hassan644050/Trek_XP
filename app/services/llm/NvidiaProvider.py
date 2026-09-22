from openai import (
    OpenAI,
    RateLimitError,
    OpenAIError,
    APIConnectionError,
    InternalServerError,
)

from app.config import get_env_meta_info
from app.services.llm.base import LLMProvider
from app.services.llm.retry import retry_on_transient
from app.exceptions.exceptions import (
    LLMRateLimitException,
    LLMProviderException,
)


class NvidiaProvider(LLMProvider):

    def __init__(self):
        env = get_env_meta_info()

        self.client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=env.llm_api_key
        )

        self.model = env.llm_model

    @retry_on_transient(InternalServerError, APIConnectionError)
    def _call(self, prompt: str):
        return self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2,
            max_tokens=1024,
            extra_body={
                "chat_template_kwargs": {
                    "enable_thinking": False
                }
            }
        )

    def generate(self, prompt: str) -> str:

        try:

            response = self._call(prompt)
            text = response.choices[0].message.content

            if not text:
                raise LLMProviderException(
                    "The model returned an empty response."
                )

            return text

        except RateLimitError as exc:
            raise LLMRateLimitException(
                "LLM rate limit exceeded."
            ) from exc

        except OpenAIError as exc:
            raise LLMProviderException(
                "LLM provider request failed."
            ) from exc
