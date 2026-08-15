"""FastAPI application entry point.

Run with:
    uvicorn app.main:app --app-dir backend --reload

or via ./scripts/run_backend.sh
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import __version__
from app.api import auth
from app.config import settings
from app.database import engine, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger("bridgetalk")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown work.

    Everything expensive or fallible happens here, once, rather than on the
    first request. In later phases this is also where the Keras model is loaded
    into memory — loading it per request would add seconds of latency to a
    system whose whole point is sub-second response.
    """
    logger.info("BridgeTalk backend v%s starting", __version__)

    # Fail fast and legibly if the database is unreachable. Without this check
    # the server starts happily and every request dies with a stack trace,
    # which is a much harder thing to debug ten minutes before a review.
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("Database connection OK")
    except Exception as exc:  # noqa: BLE001 - we genuinely want any failure here
        logger.error("Database connection FAILED: %s", exc)
        logger.error(
            "Check DATABASE_URL in .env, and that MySQL is running. "
            "For a database-free demo, set DATABASE_URL=sqlite:///./bridgetalk.db"
        )
        raise

    init_db()
    logger.info("Tables verified")

    yield

    logger.info("BridgeTalk backend shutting down")
    engine.dispose()


app = FastAPI(
    title="BridgeTalk API",
    version=__version__,
    description=(
        "Real-time sign language to text translation for deaf and hearing "
        "participants.\n\n"
        "**Privacy note:** the sign-recognition WebSocket receives hand *landmark "
        "coordinates* only. Video frames never leave the browser."
    ),
    lifespan=lifespan,
)

# CORS: the browser refuses cross-origin requests unless the server explicitly
# opts in. The frontend runs on :5173 and the API on :8000, so those are
# different origins even though both are localhost.
#
# allow_credentials=True together with an explicit origin list (never "*") is
# required for the browser to send our Authorization header on these requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)


@app.get("/health", tags=["system"], summary="Liveness and database probe")
def health() -> dict:
    """Report whether the API and its database are up.

    Used by the frontend's status panel and by the demo pre-flight check. It
    reports database status as a field rather than returning 503, so a
    half-working system is still diagnosable from one request.
    """
    database_ok = True
    database_error = None
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        database_ok = False
        database_error = str(exc)

    return {
        "status": "ok" if database_ok else "degraded",
        "version": __version__,
        "database": "connected" if database_ok else "unreachable",
        "database_error": database_error,
        # Handy during the review: proves which backend the frontend reached.
        "dialect": engine.dialect.name,
    }
