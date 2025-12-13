# Changelog
## v1.0.34
- **NEW:** Now supports Frequency Hopping via 'hop_interval' and multiple frequencies.
- **NEW:** Replaced rtl-haos revision entity with Device info
## v1.0.32
- **NEW:** Added "-F", "log" so warnings/errors appear in stdout alongside the JSON data.
- **FIX:** Improved radio status will not become unavailable.
## v1.0.31
- **NEW:** Added entity cleanup under host device.
## v1.0.19
- **NEW:** Added `BRIDGE_ID` configuration to keep the Device ID static across reboots.
- **NEW:** Added `BRIDGE_NAME` to allow custom friendly names (ignoring the Docker hostname).
- **NEW:** Improved log printout.
- **FIX:** Improved stability of the RTL-SDR auto-detection.
- **FIX:** rtl-haos revision entity should not time out.
## v1.0.0
- Initial public release.
