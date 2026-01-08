# Dual-purpose Dockerfile: Home Assistant Add-on + Standalone Docker
#
# NOTE: We build rtl_433 from upstream git so we can enable optional SoapySDR
# support (useful for Soapy-supported radios like HackRF, LimeSDR, PlutoSDR,
# SoapyRemote, etc.).

ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.21

# ==========================================================================
# STAGE 0: Build rtl_433 (and an optional SoapyHackRF module)
# ==========================================================================
FROM ${BUILD_FROM} AS rtl433_builder

ARG RTL433_GIT_URL="https://github.com/merbanan/rtl_433.git"
ARG RTL433_REF="master"

# SoapyHackRF is not packaged in Alpine v3.21, so we build it from source to
# make HackRF usable via SoapySDR.
ARG BUILD_SOAPYHACKRF="1"
ARG SOAPYHACKRF_GIT_URL="https://github.com/pothosware/SoapyHackRF.git"
ARG SOAPYHACKRF_REF="master"

RUN apk add --no-cache \
    build-base \
    cmake \
    git \
    pkgconf \
    libusb-dev \
    librtlsdr-dev \
    soapy-sdr \
    soapy-sdr-dev \
    soapy-sdr-libs \
    hackrf-dev \
    hackrf-libs

# Build and install SoapyHackRF (optional)
RUN set -eux; \
    if [ "${BUILD_SOAPYHACKRF}" = "1" ]; then \
      git clone --depth 1 --branch "${SOAPYHACKRF_REF}" "${SOAPYHACKRF_GIT_URL}" /tmp/SoapyHackRF; \
      cmake -S /tmp/SoapyHackRF -B /tmp/SoapyHackRF/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr; \
      cmake --build /tmp/SoapyHackRF/build -j"$(nproc)"; \
      cmake --install /tmp/SoapyHackRF/build; \
      rm -rf /tmp/SoapyHackRF; \
    fi

# Build and install rtl_433 with Soapy enabled
RUN set -eux; \
    git clone --branch "${RTL433_REF}" "${RTL433_GIT_URL}" /tmp/rtl_433; \
    cmake -S /tmp/rtl_433 -B /tmp/rtl_433/build \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/usr \
      -DENABLE_SOAPYSDR=ON; \
    cmake --build /tmp/rtl_433/build -j"$(nproc)"; \
    cmake --install /tmp/rtl_433/build; \
    strip /usr/bin/rtl_433 || true; \
    rm -rf /tmp/rtl_433

# ==========================================================================
# STAGE 1: Builder - Install Python dependencies with compilation support
# ==========================================================================
FROM ${BUILD_FROM} AS builder

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

# ==========================================================================
# STAGE 2: Runtime - Slim final image
# ==========================================================================
FROM ${BUILD_FROM}

# Runtime dependencies needed by rtl_433 + SoapySDR + USB access
RUN apk add --no-cache \
    rtl-sdr \
    libusb \
    soapy-sdr \
    soapy-sdr-libs \
    hackrf-libs

# Copy rtl_433 (and any Soapy modules we built) from the build stage
COPY --from=rtl433_builder /usr/bin/rtl_433 /usr/bin/rtl_433
COPY --from=rtl433_builder /usr/lib/SoapySDR /usr/lib/SoapySDR

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
