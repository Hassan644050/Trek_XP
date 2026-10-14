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


class DatabaseNotConfiguredException(AppException):
    """Raised when a database-backed feature runs without DATABASE_URL."""


class NotAuthenticatedException(AppException):
    """Raised when a request needs a signed-in user and has none."""


class InvalidCredentialsException(AppException):
    """Raised when an email/password pair does not match an active user."""


class AccountLockedException(AppException):
    """Raised after too many failed sign-in attempts."""


class PermissionDeniedException(AppException):
    """Raised when a signed-in user lacks the role an action needs."""


class ResourceNotFoundException(AppException):
    """Raised when a requested record does not exist."""


class ResourceConflictException(AppException):
    """Raised when a write would break a uniqueness rule."""


class InvalidImageException(AppException):
    """Raised when an uploaded file is not an acceptable image."""


class InvalidInputException(AppException):
    """Raised when input passes schema validation but breaks a business rule."""


class LLMTimeoutException(LLMException):
    """Raised when the model did not answer within the time allowed."""
