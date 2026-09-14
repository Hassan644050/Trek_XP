from abc import ABC, abstractmethod

from app.models.context import TripContext
from app.models.recommendation import Recommendation


class GadgetSource(ABC):
    """A source of gadget recommendations for a trip.

    This is the seam for the community catalog. v1 ships LLMGadgetSource,
    which asks a hosted model. The community-curated, coordinator-verified
    catalog plugs in behind this same interface later, so each returned
    Recommendation can carry its own provenance (origin / verified) without
    the route knowing which source produced it.
    """

    @abstractmethod
    def recommend(self, context: TripContext) -> list[Recommendation]:
        """Return gadget recommendations for the given trip context."""
