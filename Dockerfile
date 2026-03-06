# Claw Fact Bus - Production Dockerfile
# Multi-stage build for minimal image size

# -----------------------------------------------------------------------------
# Stage 1: Build dependencies
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi>=0.110 \
    uvicorn[standard]>=0.27 \
    websockets>=12.0 \
    pydantic>=2.0

# -----------------------------------------------------------------------------
# Stage 2: Runtime image
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Create non-root user for security
RUN groupadd -r bus && useradd -r -g bus bus

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code
COPY src/ ./src/
COPY pyproject.toml .

# Create data directory with proper permissions
RUN mkdir -p /data && chown -R bus:bus /data

# Switch to non-root user
USER bus

# Environment configuration
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV FACT_BUS_DATA_DIR=/data
ENV FACT_BUS_HOST=0.0.0.0
ENV FACT_BUS_PORT=8080

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Run server
CMD ["uvicorn", "claw_fact_bus.server.main:app", "--host", "0.0.0.0", "--port", "8080", "--loop", "asyncio"]
