from types import SimpleNamespace

import pytest
from google.genai import types as genai_types

from app.exceptions.exceptions import LLMProviderException, LLMRateLimitException
from app.services.llm.gemini import GeminiProvider


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.configs = []

    def generate_content(self, model, contents, config):
        self.configs.append(config)
        if self.error is not None:
            raise self.error
        return self.response


def provider_with(models):
    # Skip __init__: it builds a real client from the environment.
    provider = GeminiProvider.__new__(GeminiProvider)
    provider.client = SimpleNamespace(models=models)
    provider.model = "gemini-test"
    return provider


def reply(text, finish_reason=genai_types.FinishReason.STOP):
    return SimpleNamespace(text=text, candidates=[SimpleNamespace(finish_reason=finish_reason)])


def test_complete_reply_is_returned():
    assert provider_with(FakeModels(reply("[]"))).generate("prompt") == "[]"


def test_thinking_is_kept_minimal_so_it_cannot_eat_the_output_budget():
    models = FakeModels(reply("[]"))
    provider_with(models).generate("prompt")

    config = models.configs[0]
    assert config.thinking_config.thinking_level == genai_types.ThinkingLevel.MINIMAL
    assert config.max_output_tokens == 2000


def test_truncated_reply_is_reported_as_truncated():
    models = FakeModels(reply('[{"gadget": "Adapt', genai_types.FinishReason.MAX_TOKENS))

    with pytest.raises(LLMProviderException, match="truncated"):
        provider_with(models).generate("prompt")


def test_empty_reply_is_an_error():
    with pytest.raises(LLMProviderException, match="empty"):
        provider_with(FakeModels(reply(""))).generate("prompt")


def test_quota_error_maps_to_rate_limit():
    models = FakeModels(error=RuntimeError("429 RESOURCE_EXHAUSTED"))

    with pytest.raises(LLMRateLimitException):
        provider_with(models).generate("prompt")
