from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_media_settings
from app.handlers.exception_handlers import register_exception_handlers
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.coordinator import router as coordinator_router
from app.routes.destinations import router as destinations_router
from app.routes.health import router as health_router
from app.routes.recommend import router as recommend_router
from app.services.media.storage import LocalImageStorage, get_image_storage


app = FastAPI(
    title="Trek_XP API",
    version="0.1.0",
    description=(
        "Recommends the gadgets you actually need for a trip, based on "
        "where you are going, when, and what you plan to do there."
    ),
)

register_exception_handlers(app)

app.include_router(recommend_router)
app.include_router(destinations_router)
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
