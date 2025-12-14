# Dual-purpose Dockerfile: Home Assistant Add-on + Standalone Docker

# ============================================================================
# STAGE 1: Builder - Install Python dependencies with compilation support
# ============================================================================
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.21
FROM ${BUILD_FROM} as builder

# Install build dependencies needed for compiling Python packages
RUN apk add --no-cache \
    gcc \
    musl-dev \
    linux-headers \
    python3-dev

# Copy uv from official image
COPY --from=ghcr.io/astral-sh/uv:0.9.16 /uv /uvx /bin/

WORKDIR /app

# Copy dependency files and install into virtual environment
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ============================================================================
# STAGE 2: Runtime - Slim final image
# ============================================================================
FROM ${BUILD_FROM}

# Install only runtime dependencies
RUN apk add --no-cache \
    rtl-sdr \
    rtl_433 \
    libusb

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY *.py ./
COPY config.yaml ./
COPY run.sh /

RUN chmod a+x /run.sh

# Use the virtual environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV TERM=xterm-256color

CMD [ "/run.sh" ]
