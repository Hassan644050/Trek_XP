from app.services.gadgets.base import GadgetSource
from app.services.gadgets.llm_source import LLMGadgetSource


_gadget_source: GadgetSource | None = None


def get_gadget_source() -> GadgetSource:
    """Return the configured gadget source.

    One implementation today. When the community catalog lands, the choice
    between sources -- or the merge of both -- happens here, and nothing
    upstream has to change.
    """
    global _gadget_source

    if _gadget_source is None:
        _gadget_source = LLMGadgetSource()

    return _gadget_source
