#!/bin/sh
set -eu

# Keep version display consistent with add-on mode
if [ -z "${RTL_HAOS_BUILD:-}" ] && [ -f /app/build.txt ]; then
  RTL_HAOS_BUILD="$(tr -d '\r\n' < /app/build.txt)"
  export RTL_HAOS_BUILD
fi

echo "[STARTUP] RTL-HAOS (standalone)"
echo "[STARTUP] MQTT Host: ${MQTT_HOST:-localhost}:${MQTT_PORT:-1883}"

exec python3 /app/main.py
