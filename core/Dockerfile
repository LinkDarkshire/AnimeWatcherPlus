# AnimeWatcherPlus server: the core running standalone (e.g. on a NAS),
# for the desktop and Android apps to connect to. See deploy/ for a
# docker-compose example and the SWAG reverse proxy config.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AWP_MODE=server \
    AWP_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml alembic.ini run.py ./
COPY app ./app
COPY alembic ./alembic
RUN pip install --no-cache-dir . \
    && mkdir -p /data /media

# 8784: API -- devices in the LAN connect to it directly, from the internet
#       it's reached through the reverse proxy.
# 8785: pairing, LAN only -- never forward it.
EXPOSE 8784 8785
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8784/health')"

CMD ["python", "run.py", "--server"]
