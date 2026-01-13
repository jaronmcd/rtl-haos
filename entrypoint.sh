#!/bin/sh
set -eu

# If we're running as a Home Assistant add-on, Supervisor mounts /data/options.json
# and the HA base images provide with-contenv + bashio.
if [ -f /data/options.json ] && [ -x /usr/bin/with-contenv ]; then
  exec /run.sh
fi

# Standalone Docker mode (Compose, plain Docker, etc.)
exec /run-standalone.sh
