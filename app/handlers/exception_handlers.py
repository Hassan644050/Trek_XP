import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.exceptions import (
    DestinationDataException,
    DestinationNotFoundException,
    GadgetSourceException,
    LLMException,
    LLMRateLimitException,
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


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        DestinationNotFoundException, destination_not_found_handler
    )
    app.add_exception_handler(
        DestinationDataException, destination_data_handler
    )
    # Registered before the LLMException base so it wins for rate limits.
    app.add_exception_handler(LLMRateLimitException, rate_limit_handler)
    app.add_exception_handler(LLMException, advisor_unavailable_handler)
    app.add_exception_handler(
        GadgetSourceException, advisor_unavailable_handler
    )
