#!/usr/bin/with-contenv bashio
# shellcheck shell=bash

# Auto-set RTL_HAOS_BUILD from a build file shipped in the image (for HAOS/local add-on dev).
# This avoids relying on Docker build args (which Supervisor may not pass for local add-ons).
if [ -z "${RTL_HAOS_BUILD:-}" ] && [ -f /app/build.txt ]; then
    export RTL_HAOS_BUILD="$(tr -d '\r\n' < /app/build.txt)"
fi


# Log helper: use bashio logging in HAOS add-on mode, fall back to stdout otherwise.
log_info() {
    if [ "$(type -t bashio::log.info || true)" = "function" ]; then
        bashio::log.info "$1"
    else
        echo "[INFO] $1"
    fi
}

log_warn() {
    if [ "$(type -t bashio::log.warning || true)" = "function" ]; then
        bashio::log.warning "$1"
    else
        echo "[WARN] $1"
    fi
}

log_debug() {
    if [ "$(type -t bashio::log.debug || true)" = "function" ]; then
        bashio::log.debug "$1"
    else
        echo "[DEBUG] $1"
    fi
}

log_rtl433_version() {
    if command -v rtl_433 >/dev/null 2>&1; then
        # rtl_433 -V prints the version string and exits.
        local v
        v="$(rtl_433 -V 2>&1 | head -n 1 | tr -d '\r\n')"
        if [ -n "${v}" ]; then
            log_info "rtl_433: ${v}"
        else
            log_warn "rtl_433: version unavailable (rtl_433 -V returned empty output)"
        fi
    else
        log_warn "rtl_433 not found in PATH"
    fi
}


# Detect if running as Home Assistant Add-on
if [ -f /data/options.json ]; then
    # Home Assistant Add-on mode
    bashio::log.info "Running in Home Assistant Add-on mode"

    # Only export config values if they are set (let pydantic use defaults for empty ones)
    if bashio::config.has_value 'mqtt_host'; then
        export MQTT_HOST=$(bashio::config 'mqtt_host')
    fi

    if bashio::config.has_value 'mqtt_port'; then
        export MQTT_PORT=$(bashio::config 'mqtt_port')
    fi

    if bashio::config.has_value 'mqtt_user'; then
        export MQTT_USER=$(bashio::config 'mqtt_user')
    fi

    if bashio::config.has_value 'mqtt_pass'; then
        export MQTT_PASS=$(bashio::config 'mqtt_pass')
    fi

    if bashio::config.has_value 'rtl_expire_after'; then
        export RTL_EXPIRE_AFTER=$(bashio::config 'rtl_expire_after')
    fi

    if bashio::config.has_value 'rtl_throttle_interval'; then
        export RTL_THROTTLE_INTERVAL=$(bashio::config 'rtl_throttle_interval')
    fi

    if bashio::config.has_value 'debug_raw_json'; then
        export DEBUG_RAW_JSON=$(bashio::config 'debug_raw_json')
    fi

    # Handle array configs
    # For arrays, use jq to read directly from /data/options.json to ensure proper JSON format
    CONFIG_PATH="/data/options.json"

    export RTL_CONFIG=$(jq -c '.rtl_config // []' "$CONFIG_PATH")
    bashio::log.debug "RTL_CONFIG=${RTL_CONFIG}"

    export DEVICE_BLACKLIST=$(jq -c '.device_blacklist // ["SimpliSafe*","EezTire*"]' "$CONFIG_PATH")
    bashio::log.debug "DEVICE_BLACKLIST=${DEVICE_BLACKLIST}"

    export DEVICE_WHITELIST=$(jq -c '.device_whitelist // []' "$CONFIG_PATH")
    bashio::log.debug "DEVICE_WHITELIST=${DEVICE_WHITELIST}"

    # Use MQTT service if available and no host configured
    # Check if MQTT_HOST was exported (i.e., user provided a non-empty value)
    if [ -z "${MQTT_HOST:-}" ] && bashio::services.available "mqtt"; then
        bashio::log.info "Using Home Assistant MQTT service"
        export MQTT_HOST=$(bashio::services mqtt "host")
        export MQTT_PORT=$(bashio::services mqtt "port")
        export MQTT_USER=$(bashio::services mqtt "username")
        export MQTT_PASS=$(bashio::services mqtt "password")
        export BRIDGE_ID=$(bashio::config 'bridge_id')
        export BRIDGE_NAME=$(bashio::config 'bridge_name')
    fi

    bashio::log.info "Starting RTL-HAOS bridge..."
    bashio::log.info "MQTT Host: ${MQTT_HOST:-none}:${MQTT_PORT:-none}"
    log_rtl433_version
else
    # Standalone Docker mode - use environment variables directly
    echo "[STARTUP] Running in standalone mode"
    echo "[STARTUP] MQTT Host: ${MQTT_HOST:-localhost}:${MQTT_PORT:-1883}"
    log_rtl433_version
fi

exec python3 /app/main.py
