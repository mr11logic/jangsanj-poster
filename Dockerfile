# JangSanj Poster Service — Docker image
# Works on Render, Railway, Fly.io, Google Cloud Run, AWS App Runner,
# or any host that runs Docker.

FROM python:3.11-slim

# libraqm is already bundled in Pillow's manylinux wheels, but we install
# the system libraries anyway so re-installing Pillow from source (if a
# wheel is unavailable) still picks up raqm support.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libraqm0 libfreetype6 libharfbuzz0b libfribidi0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && python3 -c "from PIL import features; assert features.check('raqm'), 'Pillow must be built with raqm'"

# Copy the service code
COPY app.py poster.py date_utils.py config.json run.sh ./
COPY fonts/  ./fonts/
COPY templates/ ./templates/
RUN mkdir -p output && chmod +x run.sh

# Render / Cloud Run set the PORT env var; default to 8000 for local runs.
ENV PORT=8000
ENV HOST=0.0.0.0
EXPOSE 8000

# Run via uvicorn directly (works in all containers).
CMD ["sh", "-c", "uvicorn app:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]
