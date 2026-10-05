from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from app.config import get_env_meta_info
from app.services.llm.base import LLMProvider
from app.services.llm.retry import retry_on_transient


# A safety bound, not a cost optimisation: without it a runaway response is
# unbounded spend. Set well above what eight items need (~450 tokens) because
# on thinking-capable models reasoning is drawn from this same budget, and a
# budget spent thinking truncates the JSON mid-array.
#
# Routine cost is controlled by asking for fewer, shorter items instead --
# see MAX_ITEMS and MAX_WHY_WORDS in the gadget prompt.
MAX_OUTPUT_TOKENS = 2000

# Low but not zero: the same trip should produce a stable list, which also
# makes cached answers representative of what an uncached one would say.
TEMPERATURE = 0.3

# Gemini 3 models think by default, and that thinking draws on the output
# budget above: measured on a three-day Kaptai Lake trip, ~1,800 of the
# 2,000 tokens went to thinking and the gadget list was cut off mid-array.
# A grounded list does not need deliberation -- MINIMAL produced complete,
# equally specific lists with no thinking tokens. (Gemini 3 setting; 2.5
# models use thinking_budget instead.)
THINKING_LEVEL = genai_types.ThinkingLevel.MINIMAL
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
            config=genai_types.GenerateContentConfig(
                max_output_tokens=MAX_OUTPUT_TOKENS,
                temperature=TEMPERATURE,
                thinking_config=genai_types.ThinkingConfig(
                    thinking_level=THINKING_LEVEL
                ),
            ),
        )

    def generate(self, prompt: str) -> str:
        try:

            response = self._call(prompt)
            text = response.text

            candidates = response.candidates or []
            finish_reason = candidates[0].finish_reason if candidates else None

            if finish_reason == genai_types.FinishReason.MAX_TOKENS:
                # Say so plainly: otherwise this surfaces later as an
                # unreadable-JSON error that hides the real cause.
                raise LLMProviderException(
                    "The model's response was truncated at the output limit."
                )

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

