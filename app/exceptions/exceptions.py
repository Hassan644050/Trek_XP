class AppException(Exception):
    """Base exception for application-specific errors."""


class DestinationDataException(AppException):
    """Raised when destination data (climate / country) cannot be retrieved."""


class GadgetSourceException(AppException):
    """Raised when a gadget source cannot produce recommendations."""


class LLMException(AppException):
    """Raised when the LLM service cannot be used."""


class LLMRateLimitException(LLMException):
    """Raised when the LLM rate limit is exceeded."""


class LLMProviderException(LLMException):
    """Raised when the LLM provider returns an error."""
