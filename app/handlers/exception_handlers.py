from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.exceptions import (
    DestinationDataException,
    DestinationNotFoundException,
    GadgetSourceException,
    LLMException,
)


async def destination_not_found_handler(
    request: Request,
    exc: DestinationNotFoundException,
) -> JSONResponse:
    # The caller asked about a place that does not resolve -- their input,
    # not our outage.
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


async def upstream_unavailable_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc)},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        DestinationNotFoundException, destination_not_found_handler
    )
    app.add_exception_handler(
        DestinationDataException, upstream_unavailable_handler
    )
    app.add_exception_handler(
        GadgetSourceException, upstream_unavailable_handler
    )
    app.add_exception_handler(LLMException, upstream_unavailable_handler)
