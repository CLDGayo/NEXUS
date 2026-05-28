"""NEXUS Knowledge Base — FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from integrations import dispatcher as integrations_dispatcher  # noqa: E402
from routers import (  # noqa: E402
    api_tokens,
    auth,
    changelog,
    chat,
    chat_uploads,
    conversations,
    dashboard,
    documents,
    health,
    integrations,
    logs,
    resources,
    settings,
    uploads,
)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    integrations_dispatcher.register()
    yield


app = FastAPI(title="NEXUS Knowledge Base", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,          prefix="/api/auth")
app.include_router(health.router,        prefix="/api")
app.include_router(chat.router,          prefix="/api/chat")
app.include_router(chat_uploads.router,  prefix="/api/chat")
app.include_router(dashboard.router,     prefix="/api/dashboard")
app.include_router(documents.router,     prefix="/api")
app.include_router(uploads.router,       prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(logs.router,          prefix="/api")
app.include_router(settings.router,      prefix="/api/settings")
app.include_router(changelog.router,     prefix="/api/changelog")
app.include_router(integrations.router,  prefix="/api/integrations")
app.include_router(api_tokens.router,    prefix="/api/tokens")
app.include_router(resources.router,     prefix="/api/resources")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/widget", include_in_schema=False)
async def widget() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "widget.html"))


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/{_:path}", include_in_schema=False)
async def spa(_: str = "") -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))
