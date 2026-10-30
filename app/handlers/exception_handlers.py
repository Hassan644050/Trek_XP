import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.exceptions import (
    AccountLockedException,
    DatabaseNotConfiguredException,
    DestinationDataException,
    DestinationNotFoundException,
    GadgetSourceException,
    ImageStorageException,
    InvalidCredentialsException,
    InvalidImageException,
    InvalidInputException,
    LLMException,
    LLMRateLimitException,
    LLMTimeoutException,
    NotAuthenticatedException,
    PermissionDeniedException,
    ResourceConflictException,
    ResourceNotFoundException,
    OutOfStockException,
    TooManyRequestsException,
)


logger = logging.getLogger(__name__)


def _problem(
    request: Request,
    exc: Exception,
    code: int,
    message: str,
) -> JSONResponse:
    """Log what actually happened; tell the caller something useful.

    Internal messages name the provider and the failure mode, which is what
    we want in the logs and not what a traveller should have to read.
    """
    logger.warning("%s on %s: %s", type(exc).__name__, request.url.path, exc)

    return JSONResponse(status_code=code, content={"detail": message})


async def destination_not_found_handler(
    request: Request,
    exc: DestinationNotFoundException,
) -> JSONResponse:
    # Already phrased for the person who typed it.
    return _problem(request, exc, status.HTTP_404_NOT_FOUND, str(exc))


async def destination_data_handler(
    request: Request,
    exc: DestinationDataException,
) -> JSONResponse:
    return _problem(
        request,
        exc,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "We could not look up that destination just now. Please try again.",
    )


async def rate_limit_handler(
    request: Request,
    exc: LLMRateLimitException,
) -> JSONResponse:
    return _problem(
        request,
        exc,
        status.HTTP_429_TOO_MANY_REQUESTS,
        "We have reached today's limit for new packing lists. "
        "Please try again later.",
    )


async def advisor_timeout_handler(
    request: Request,
    exc: LLMTimeoutException,
) -> JSONResponse:
    return _problem(
        request,
        exc,
        status.HTTP_504_GATEWAY_TIMEOUT,
        "The gear advisor is taking longer than usual. Please try again.",
    )


async def advisor_unavailable_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _problem(
        request,
        exc,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "The gear advisor is unavailable right now. "
        "Please try again in a moment.",
    )


def _passthrough(code: int):
    """Handler for errors whose message is already written for the user."""

    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return _problem(request, exc, code, str(exc))

    return handler


async def database_unavailable_handler(
    request: Request,
    exc: DatabaseNotConfiguredException,
) -> JSONResponse:
    return _problem(
        request,
        exc,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "The coordinator area is not available right now.",
    )


async def image_storage_handler(
    request: Request,
    exc: ImageStorageException,
) -> JSONResponse:
    return _problem(
        request,
        exc,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "The image store is unavailable right now. "
        "The gadget was saved; please try the image again.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    for exc_class, code in (
        (NotAuthenticatedException, status.HTTP_401_UNAUTHORIZED),
        (InvalidCredentialsException, status.HTTP_401_UNAUTHORIZED),
        (AccountLockedException, status.HTTP_429_TOO_MANY_REQUESTS),
        (PermissionDeniedException, status.HTTP_403_FORBIDDEN),
        (ResourceNotFoundException, status.HTTP_404_NOT_FOUND),
        (ResourceConflictException, status.HTTP_409_CONFLICT),
        (InvalidImageException, status.HTTP_422_UNPROCESSABLE_CONTENT),
        (InvalidInputException, status.HTTP_422_UNPROCESSABLE_CONTENT),
        (OutOfStockException, status.HTTP_409_CONFLICT),
        (TooManyRequestsException, status.HTTP_429_TOO_MANY_REQUESTS),
    ):
        app.add_exception_handler(exc_class, _passthrough(code))

    app.add_exception_handler(DatabaseNotConfiguredException, database_unavailable_handler)
    app.add_exception_handler(ImageStorageException, image_storage_handler)

    app.add_exception_handler(
        DestinationNotFoundException, destination_not_found_handler
    )
    app.add_exception_handler(
        DestinationDataException, destination_data_handler
    )
    # Registered before the LLMException base so the specific subclasses win.
    app.add_exception_handler(LLMRateLimitException, rate_limit_handler)
    app.add_exception_handler(LLMTimeoutException, advisor_timeout_handler)
    app.add_exception_handler(LLMException, advisor_unavailable_handler)
    app.add_exception_handler(
        GadgetSourceException, advisor_unavailable_handler
    )
