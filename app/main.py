"""FastAPI application entrypoint."""

from fastapi import FastAPI

app = FastAPI(title="mcareers", version="0.1.0")


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok"}
