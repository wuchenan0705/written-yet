import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from app import config, line_bot, push, scheduler, web
from app.db import init_db

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if config.LINE_CHANNEL_ACCESS_TOKEN:
        push.set_transport(line_bot.LineTransport(config.LINE_CHANNEL_ACCESS_TOKEN))
    sched = None if config.DISABLE_SCHEDULER else scheduler.start()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware, secret_key=config.SESSION_SECRET, max_age=60 * 60 * 24 * 30,
    https_only=config.BASE_URL.startswith("https://"),
)
app.include_router(line_bot.router)
app.include_router(web.router)


@app.exception_handler(web.LoginRequired)
async def _login_required(request: Request, exc: web.LoginRequired):
    return RedirectResponse("/login", 303)


@app.get("/health")
def health():
    return {"ok": True}
