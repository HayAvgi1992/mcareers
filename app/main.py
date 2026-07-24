"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.db.session import check_db, dispose_engine
from app.logging_config import configure_logging
from app.queue.client import QueueClient

configure_logging()

app = FastAPI(title="mcareers", version="0.1.0")

app.include_router(jobs_router)
app.include_router(health_router)


@app.on_event("startup")
async def startup() -> None:
    await check_db()
    queue = await QueueClient.connect()
    app.state.queue = queue


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.queue.close()
    await dispose_engine()


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok"}
