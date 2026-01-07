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
# STAGE 2: rtl_433 builder - build rtl_433 from upstream git
# ============================================================================
FROM ${BUILD_FROM} as rtl433_builder

# Set this to a tag/branch/commit SHA you want, e.g. "master", "25.02", or a full SHA.
ARG RTL433_GIT_REF=master

RUN apk add --no-cache \
    git \
    build-base \
    cmake \
    pkgconf \
    libusb-dev \
    librtlsdr-dev

WORKDIR /tmp

RUN git clone https://github.com/merbanan/rtl_433.git /tmp/rtl_433 \
    && cd /tmp/rtl_433 \
    && git checkout "${RTL433_GIT_REF}" \
    && cmake -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    && cmake --build build \
    && DESTDIR=/tmp/rtl433-install cmake --install build

# ============================================================================
# STAGE 3: Runtime - Slim final image
# ============================================================================
FROM ${BUILD_FROM}

# Install only runtime dependencies (NOTE: no rtl_433 apk package)
RUN apk add --no-cache \
    rtl-sdr \
    libusb

# Copy rtl_433 binary built from git
COPY --from=rtl433_builder /tmp/rtl433-install/usr/bin/rtl_433 /usr/bin/rtl_433

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY . ./
COPY run.sh /

# Optional internal build metadata (SemVer build metadata). Kept out of config.yaml.
ARG RTL_HAOS_BUILD=""
ENV RTL_HAOS_BUILD="${RTL_HAOS_BUILD}"

# Create /app/build.txt for display version (vX.Y.Z+<build>) without requiring runtime git.
RUN set -eu; \
    if [ -n "${RTL_HAOS_BUILD}" ]; then \
        printf "%s" "${RTL_HAOS_BUILD}" > /app/build.txt; \
    elif [ -f /app/.git/HEAD ]; then \
        headref="$(tr -d '\r\n' < /app/.git/HEAD)"; \
        sha=""; \
        case "${headref}" in \
            ref:*) \
                refpath="${headref#ref: }"; \
                if [ -f "/app/.git/${refpath}" ]; then \
                    sha="$(tr -d '\r\n' < "/app/.git/${refpath}")"; \
                elif [ -f /app/.git/packed-refs ]; then \
                    sha="$(grep " ${refpath}$" /app/.git/packed-refs 2>/dev/null | head -n 1 | awk '{print $1}')"; \
                fi; \
                ;; \
            *) \
                sha="${headref}"; \
                ;; \
        esac; \
        sha="$(printf "%s" "${sha}" | tr -d '\r\n')"; \
        if [ -n "${sha}" ]; then \
            printf "%s" "${sha}" | cut -c1-7 > /app/build.txt; \
        fi; \
    fi; \
    rm -rf /app/.git

RUN chmod a+x /run.sh

# Use the virtual environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV TERM=xterm-256color

CMD [ "/run.sh" ]
