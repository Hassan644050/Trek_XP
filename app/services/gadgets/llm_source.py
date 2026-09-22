import json

from app.exceptions.exceptions import GadgetSourceException
from app.models.context import TripContext
from app.models.recommendation import Origin, Priority, Recommendation
from app.services.gadgets.base import GadgetSource
from app.services.gadgets.prompt import build_gadget_prompt
from app.services.llm.base import LLMProvider
from app.services.llm.factory import get_llm_provider


def _strip_fences(raw: str) -> str:
    text = raw.strip()

    if not text.startswith("```"):
        return text

    # ```json\n[...]\n``` -> [...]
    body = text.split("\n", 1)[1] if "\n" in text else ""

    return body.rsplit("```", 1)[0].strip()


def _extract_array(text: str) -> str:
    start = text.find("[")
    end = text.rfind("]")

    if start == -1 or end == -1 or end < start:
        return text

    return text[start : end + 1]


def _coerce_priority(value: object) -> Priority:
    try:
        return Priority(str(value).strip().lower())
    except ValueError:
        return Priority.RECOMMENDED


def parse_recommendations(raw: str) -> list[Recommendation]:
    """Turn a model's reply into Recommendations.

    Models wrap JSON in fences or add a sentence of preamble often enough
    that this strips both before parsing. Individual malformed entries are
    skipped rather than failing the whole batch; only a completely
    unparseable reply is an error.
    """
    payload = _extract_array(_strip_fences(raw))

    try:
        items = json.loads(payload)
    except ValueError as exc:
        raise GadgetSourceException(
            "The gadget advisor returned a response we could not read."
        ) from exc

    if not isinstance(items, list):
        raise GadgetSourceException(
            "The gadget advisor returned an unexpected response shape."
        )

    recommendations: list[Recommendation] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        gadget = str(item.get("gadget", "")).strip()
        why = str(item.get("why", "")).strip()

        if not gadget or not why:
            continue

        category = item.get("category")

        recommendations.append(
            Recommendation(
                gadget=gadget,
                why=why,
                priority=_coerce_priority(item.get("priority")),
                category=str(category).strip() if category else None,
                # Set here, never taken from the model: nothing the LLM
                # produces counts as community-verified.
                origin=Origin.LLM,
                verified=False,
            )
        )

    return recommendations


class LLMGadgetSource(GadgetSource):
    """Gadget recommendations from a hosted model's own knowledge.

    This is the v1 source. A community-curated catalog will implement the
    same interface, at which point items can be merged and told apart by
    their origin.
    """

    def __init__(self, provider: LLMProvider | None = None):
        # Injectable so tests can drive it without a network call.
        self._provider = provider

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = get_llm_provider()

        return self._provider

    def recommend(self, context: TripContext) -> list[Recommendation]:
        prompt = build_gadget_prompt(context)

        # LLMException propagates: the handler maps it to 503 so callers
        # know to retry rather than treating an outage as a real answer.
        raw = self.provider.generate(prompt)

        return parse_recommendations(raw)
