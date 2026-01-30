# Dual-purpose Dockerfile: Home Assistant Add-on + Standalone Docker
#
# Key idea:
# - Home Assistant add-on builds pass BUILD_FROM (via build.yaml) which points to an arch-specific
#   Home Assistant base image that includes bashio + s6-overlay.
# - Standalone Docker builds (e.g., docker compose on Debian/RPi) should work out-of-the-box on
#   amd64/arm64/armv7, so the default BUILD_FROM is a multi-arch Alpine base.
#
# The container entry command is /entrypoint.sh, which automatically switches between:
#   - /run.sh            (Home Assistant add-on mode, requires with-contenv + bashio)
#   - /run-standalone.sh (plain Docker mode, no bashio required)

# ==========================================================================
# STAGE 1: Builder - install Python deps with compilation support
# ==========================================================================
ARG BUILD_FROM=alpine:3.21
FROM ${BUILD_FROM} AS builder

# Build deps
# - python3/python3-dev: needed for standalone builds; HA base-python already includes Python,
#   but may not include headers.
#
# NOTE: On HA base images, python3 may already exist; installing python3-dev is still fine.
RUN apk add --no-cache \
    python3 \
    python3-dev \
    gcc \
    musl-dev \
    linux-headers

# Copy uv from official image
COPY --from=ghcr.io/astral-sh/uv:0.9.16 /uv /uvx /bin/

WORKDIR /app

# Copy dependency files and install into virtual environment
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ==========================================================================
# STAGE 2: Runtime
# ==========================================================================
FROM ${BUILD_FROM}

# Runtime deps
# - python3: required for standalone base; HA base already includes Python
# - rtl-sdr / rtl_433 / libusb: SDR + rtl_433
RUN set -eu; \
    if ! command -v python3 >/dev/null 2>&1; then \
        apk add --no-cache python3; \
    fi; \
    apk add --no-cache rtl-sdr rtl_433 libusb

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY . ./

# Add runtime scripts
COPY run.sh /run.sh
COPY run-standalone.sh /run-standalone.sh
COPY entrypoint.sh /entrypoint.sh
RUN chmod a+x /run.sh /run-standalone.sh /entrypoint.sh

# Optional internal build metadata (SemVer build metadata). Kept out of config.yaml.
#
# Note: Home Assistant's add-on build system provides BUILD_VERSION/BUILD_ARCH/BUILD_FROM by default,
# but does not provide a git SHA.
#
# For "HAOS pulls from git" installs, we derive a short SHA from minimal .git metadata (HEAD/refs)
# that is temporarily included via .dockerignore exceptions. We then write it to /app/build.txt and
# remove /app/.git so the final image stays clean.
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

# Use the virtual environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV TERM=xterm-256color

CMD [ "/entrypoint.sh" ]
