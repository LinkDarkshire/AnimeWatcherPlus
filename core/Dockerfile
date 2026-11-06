# AnimeWatcherPlus server: the core running standalone (e.g. on a NAS),
# for the desktop and Android apps to connect to, plus the web interface.
# See deploy/ for a docker-compose example and the SWAG reverse proxy config.
#
# Built from the repository root (the web interface comes from shell/ui):
#   docker build -f core/Dockerfile .

# The web interface: the apps' UI, built for the browser.
FROM node:22-slim AS web-ui
WORKDIR /ui
COPY shell/ui/package.json shell/ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY shell/ui ./
ENV VITE_WEB_UI=1
RUN npm run build

FROM python:3.12-slim

# Links the image on ghcr.io to the repository (its page, README, visibility).
LABEL org.opencontainers.image.source="https://github.com/LinkDarkshire/AnimeWatcherPlus" \
      org.opencontainers.image.description="AnimeWatcherPlus server: anime library for the desktop and Android apps"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AWP_MODE=server \
    AWP_DATA_DIR=/data \
    AWP_WEB_UI_DIR=/app/web

WORKDIR /app
ARG WITH_RESOLVERS=1
COPY core/pyproject.toml core/alembic.ini core/run.py ./
COPY core/app ./app
COPY core/alembic ./alembic
COPY --from=web-ui /ui/dist ./web
RUN if [ "$WITH_RESOLVERS" = "1" ]; then \
      pip install --no-cache-dir ".[resolvers]"; \
    else \
      pip install --no-cache-dir .; \
    fi \
    && mkdir -p /data /media

# 8784: API and web interface -- devices in the LAN connect to it directly,
#       from the internet it's reached through the reverse proxy.
# 8785: pairing, LAN only -- never forward it.
EXPOSE 8784 8785
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import ssl, urllib.request; urllib.request.urlopen('https://127.0.0.1:8784/health', context=ssl._create_unverified_context())"

CMD ["python", "run.py", "--server"]
