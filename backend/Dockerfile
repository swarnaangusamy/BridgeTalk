# ============================================================================
# BridgeTalk backend — FastAPI + TensorFlow + Whisper
#
#   docker build -f backend/Dockerfile -t bridgetalk-backend .
#
# Built from the REPOSITORY ROOT, not from backend/, because the app imports
# normalisation code that the ml/ training scripts also use, and reads model
# files from ml/models/. A context of backend/ alone cannot see either.
# ============================================================================
FROM python:3.11-slim AS base

# ffmpeg is a hard requirement for the Whisper speech provider: MediaRecorder
# sends compressed WebM/Opus and Whisper needs raw PCM. It is NOT a pip
# package, which is the single most common reason a working local setup fails
# in a container.
#
# libgl1 and libglib2.0-0 are needed by opencv-python, which MediaPipe pulls
# in. Without them the import fails at startup with a bare
# "libGL.so.1: cannot open shared object file".
RUN apt-get update && apt-get install --no-install-recommends -y \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Requirements first, as their own layer: dependency installs are slow
# (TensorFlow alone is ~250 MB) and must not be redone every time a source
# file changes.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Application code and the pieces it reads at runtime.
COPY backend/ ./backend/
COPY ml/scripts/ ./ml/scripts/
# Model side-cars and weights. .dockerignore keeps raw datasets out — they are
# gigabytes and are only needed for training, never for serving.
COPY ml/models/ ./ml/models/

# Non-root. The container needs no write access to anything except /tmp, which
# is where ffmpeg's intermediate audio files go.
RUN useradd --create-home --uid 10001 bridgetalk \
    && chown -R bridgetalk:bridgetalk /app
USER bridgetalk

EXPOSE 8000

# The app's own /health endpoint, which checks the database too — so an
# unhealthy database shows up as an unhealthy container rather than as a
# container that is up and failing every request.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# No --reload: that is a development convenience and it doubles memory by
# running a reloader process alongside the worker.
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
