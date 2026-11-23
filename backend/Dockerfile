# Wardenix gateway backend image
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (build tools kept minimal; re2 build deps added in P2 when enabled)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching
COPY pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install .

# App source
COPY . .

# Non-root runtime user
RUN useradd --create-home --uid 10001 wardenix \
    && chown -R wardenix:wardenix /app
USER wardenix

EXPOSE 8000

# entrypoint runs migrations then launches uvicorn
ENTRYPOINT ["/app/entrypoint.sh"]
