# Changelog
## v1.1.9  
- **FIX:** Added -M level back to rtl_433 cmd for radio signal metrics
## v1.1.8
- **NEW:** Added warning when no sdr hardware is detected
## v1.1.7
- **NEW:** Configuration warnings improvments.
## v1.1.6
- **NEW:** RTL-SDR mis-configuratrion warnings
## v1.1.5
- **FIX:** crash & JSON debug fix
## v1.1.3
- **FIX:** crash fix
## v1.1.2
- **NEW:** Add support for blocking devices based on type.
## v1.1.1
- **NEW:** verbose log toggle
- **NEW:** automatic secondary RTL-433 configured at 915Mhz
## v1.1
- **NEW:** Improved management of multiple radios
- **NEW:** Color log with colors for WARNING, ERROR, INFO, DEBUG
- **NEW:** Add-on icon
- **NEW:** Added button to reset radios
- **FIX:** Hop mode works with rtl-sdr autodetect
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
