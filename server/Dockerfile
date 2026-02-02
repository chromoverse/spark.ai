# Production-ready Dockerfile with model caching

# Stage 1: Base
FROM python:3.11-slim as base

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Model downloader
FROM base as model-downloader

# Copy app code needed for model download
COPY app/ml ./app/ml
COPY scripts ./scripts

# Download all models (cached in Docker layer)
RUN python scripts/download_models.py

# Stage 3: Final production image
FROM base as production

# Copy application code
COPY . .

# Copy downloaded models from previous stage
COPY --from=model-downloader /app/models ./models

# Make startup script executable
RUN chmod +x scripts/prod_start.sh

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start server
CMD ["./scripts/prod_start.sh"]