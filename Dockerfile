# Cloud image for the chat server (Render, Cloud Run, or any Docker host).
#
# Data (data/chroma + data/chunks.jsonl) is not in git. Two ways to get it into the image:
#   1. DATA_URL build arg: a zip (e.g. a GitHub Release asset) holding chroma/ and chunks.jsonl.
#   2. No DATA_URL: data/ next to this file is copied as is (local builds).
# Keys come from the host's secrets at runtime, never from a file or a build arg.
FROM python:3.13-slim

RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PORT=8000
WORKDIR /app

COPY --chown=user requirements.txt .
# Pin chromadb to the version the index was built with.
RUN pip install --no-cache-dir --user -r requirements.txt "chromadb==1.5.9"

COPY --chown=user config/ config/
COPY --chown=user src/ src/
COPY --chown=user data/ data/
COPY --chown=user scripts/fetch_data.py scripts/

ARG DATA_URL=""
RUN python scripts/fetch_data.py

EXPOSE 8000
CMD ["sh", "-c", "uvicorn fnx_bot.server.app:app --host 0.0.0.0 --port ${PORT}"]
