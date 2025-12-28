# Changelog

## v1.1.13
- **FIX:** Home Assistant discovery for **ERT-SCM electric meters** so they no longer appear as gas meters; they now publish as **Energy (kWh)**.
- **FIX:** **consumption readings being 100× too large** for **ERT-SCM** and **SCMplus** meters by normalizing the reported consumption value (÷100) so the sensor matches the physical meter display.

## v1.1.12
- **NEW:** Auto multi-radio: starts multiple radios when multiple RTL-SDR dongles are present.
- **NEW:** Region / Band Plan dropdown (`rtl_auto_band_plan: auto|us|eu|world`) used for Radio #2 in auto multi-mode.
- **NEW:** Treat `consumption_data` as a main sensor (improves ERT-SCM utility readings in Home Assistant).

## v1.1.11
### Fixes
- **FIX:** Restore reliable host radio status publishing.
- **FIX:** Improve JSON debug logging (safer and clearer).

### Dev tooling / tests
- **NEW:** Helper script to record `rtl_433` IQ fixtures (`scripts/record_rtl433_fixture.sh`).
- **NEW:** Expanded unit tests and added opt-in markers (`integration`, `hardware`).

### Docs
- **DOCS:** Added `docs/` pages (config, MQTT topics, multi-radio, development/testing).
- **DOCS:** README reorganized and linked to deeper docs.

## v1.1.10
### New: Low Battery alert
- **NEW:** Adds a Home Assistant **Battery Low** `binary_sensor` based on `battery_ok`.
  - HA shows **LOW** when `battery_ok=0`
  - HA shows **OK** when `battery_ok=1`
- **NEW:** **Battery clear delay** via `battery_ok_clear_after`:
  - `0` = clear LOW immediately on the next OK report
  - `>0` = LOW only clears after `battery_ok` stays OK for that many seconds (helps prevent flapping)

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
