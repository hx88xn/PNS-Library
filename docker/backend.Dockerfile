# PDAS API server.
#
# Ollama is not in this image and never should be: it owns the GPU and its
# model blobs are gigabytes. It runs as its own service and is reached over
# HTTP, which is the seam core/ollama.py was written around.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies before source. requirements.in changes rarely; the source
# changes constantly. Split this way a code edit rebuilds in seconds instead
# of re-resolving faiss, numpy and pymupdf every time.
COPY backend/requirements.in ./
RUN pip install -r requirements.in

COPY backend/ ./
# --no-deps: everything is already installed above, and this only needs to put
# the `pdas` console script on PATH for `docker compose exec`.
RUN pip install --no-deps .

# Everything mutable — SQLite database, FAISS index, stored copies of ingested
# documents — lives under one directory so a single volume covers the lot.
ENV PDAS_DATA_DIR=/data

# Not root: this process parses untrusted PDFs from a network upload.
RUN useradd --system --create-home --uid 10001 pdas \
    && mkdir -p /data \
    && chown pdas:pdas /data
USER pdas

VOLUME ["/data"]
EXPOSE 8000

CMD ["pdas", "serve", "--host", "0.0.0.0", "--port", "8000"]
