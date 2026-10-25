import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_media_settings
from app.handlers.exception_handlers import register_exception_handlers
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.coordinator import router as coordinator_router
from app.routes.destinations import router as destinations_router
from app.routes.destinations import warm_public_caches
from app.routes.gadget_pages import router as gadget_pages_router
from app.routes.health import router as health_router
from app.routes.recommend import router as recommend_router
from app.services.media.storage import LocalImageStorage, get_image_storage
from app.db.engine import get_sessionmaker
from app.exceptions.exceptions import DatabaseNotConfiguredException
from app.services import analytics
from app.services.read_cache import clear_read_caches


@asynccontextmanager
async def lifespan(_: FastAPI):
    # In the background: startup never waits on the database, and a slow or
    # unreachable one costs nothing but a cold first request.
    warm = asyncio.create_task(warm_public_caches())

    try:
        sessionmaker = get_sessionmaker()
    except DatabaseNotConfiguredException:
        sessionmaker = None
    counting = asyncio.create_task(analytics.flush_forever(get_sessionmaker)) if sessionmaker else None

    yield

    warm.cancel()
    if counting:
        counting.cancel()
        # Write what is buffered, so a deploy or restart loses no counts.
        await analytics.flush(sessionmaker)


app = FastAPI(
    lifespan=lifespan,
    title="Trek_XP API",
    version="0.1.0",
    description=(
        "Recommends the gadgets you actually need for a trip, based on "
        "where you are going, when, and what you plan to do there."
    ),
)

register_exception_handlers(app)


_CATALOG_WRITE_PREFIXES = ("/api/admin/", "/api/coordinator/")


@app.middleware("http")
async def drop_read_caches_after_catalog_writes(request: Request, call_next):
    """Any successful admin or coordinator write can change what the public
    pages show (options, destinations, hero photos), so the cached copies
    are dropped -- in one place, instead of in every write route."""
    response = await call_next(request)

    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and request.url.path.startswith(_CATALOG_WRITE_PREFIXES)
        and response.status_code < 400
    ):
        clear_read_caches()

    return response


@app.middleware("http")
async def count_page_views(request: Request, call_next):
    """Anonymous visitor counting for the public pages; see analytics.py.
    Touches only an in-memory buffer, so it adds nothing a visitor waits on."""
    response = await call_next(request)
    analytics.record_page_view(request, response.status_code)
    return response

app.include_router(recommend_router)
app.include_router(destinations_router)
app.include_router(gadget_pages_router)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(coordinator_router)
app.include_router(admin_router)


STATIC_DIR = Path(__file__).parent / "static"


@app.get("/coordinator", include_in_schema=False)
def coordinator_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "coordinator.html")


# Resolved at import so a broken image-store configuration stops the app
# at boot, rather than surfacing as a failed upload hours later.
image_storage = get_image_storage()

if isinstance(image_storage, LocalImageStorage):
    # Development only. In production R2 serves these itself, so there is
    # no local folder to create and nothing to mount.
    media = get_media_settings()
    media.directory.mkdir(parents=True, exist_ok=True)

    # Processed gadget images. Mounted before "/" so the catch-all frontend
    # mount below never shadows it.
    app.mount(
        media.url_prefix,
        StaticFiles(directory=media.directory),
        name="media",
    )

# Mounted last so it never shadows an API route.
app.mount(
    "/",
    StaticFiles(directory=STATIC_DIR, html=True),
    name="static",
)
