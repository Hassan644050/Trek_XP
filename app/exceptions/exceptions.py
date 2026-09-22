class AppException(Exception):
    """Base exception for application-specific errors."""


class DestinationDataException(AppException):
    """Raised when a destination data service cannot be reached."""


class DestinationNotFoundException(AppException):
    """Raised when the destination does not resolve to a real place."""


class GadgetSourceException(AppException):
    """Raised when a gadget source cannot produce recommendations."""


class LLMException(AppException):
    """Raised when the LLM service cannot be used."""


class LLMRateLimitException(LLMException):
    """Raised when the LLM rate limit is exceeded."""


class LLMProviderException(LLMException):
    """Raised when the LLM provider returns an error."""
