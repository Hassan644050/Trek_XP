from fastapi import FastAPI

from app.handlers.exception_handlers import register_exception_handlers
from app.routes.health import router as health_router
from app.routes.recommend import router as recommend_router


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
app.include_router(health_router)
