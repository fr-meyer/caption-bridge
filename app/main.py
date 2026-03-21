import uvicorn
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from app.config import settings

app = FastAPI(title="CaptionBridge")

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
