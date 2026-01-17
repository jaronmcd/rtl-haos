# Changelog

## v1.2.0-rc.2 (Release Candidate 2)

### HA add-on config + rtl_tcp quality-of-life
- **DOCS:** Fix invalid README YAML example (copy/paste-safe) and add explicit Home Assistant add-on `rtl_tcp` example using `device: "rtl_tcp:HOST:PORT"`.
- **FIX:** Reduce misleading config warnings for `rtl_tcp`/explicit `device` radios; harden hop interval parsing so invalid values do not break startup.
- **NEW:** Add-on schema now accepts `tcp_host`/`tcp_port` inside `rtl_config` (optional alternative to `device: rtl_tcp:...`).
- **DOCS:** Refresh `docs/CONFIG.md` to match current add-on options and `rtl_tcp` usage.
- **DOCS:** Clarify that `docker-compose.yml` defaults to **rtl_tcp/network SDR** (USB passthrough is opt-in via `privileged` + `/dev/bus/usb`).

## v1.2.0-rc.1 (Release Candidate 1)

### rtl_433 passthrough (advanced tuning & full decoder control)
- **NEW:** Optional passthrough fields to supply arbitrary `rtl_433` flags and/or a full `rtl_433` config (`-c`):
  - Global env: `RTL_433_ARGS`, `RTL_433_CONFIG_PATH`, `RTL_433_CONFIG_INLINE`, `RTL_433_BIN`
  - Per-radio overrides inside `rtl_config`: `args`, `device`, `config_path`, `config_inline`, `bin`
- **NEW:** Add-on now maps `/share` so config files can be dropped into the host share and referenced from the add-on.

### Version display: keep Supervisor comparisons stable
- **NEW:** Display version can include SemVer build metadata (e.g. `v1.2.0-rc.1+046cc83`) for logs/device info.
  - Base add-on version in `config.yaml` follows SemVer and may include a pre-release tag (e.g. `1.2.0-rc.1`). Supervisor comparisons use this value.
  - Build metadata can be provided via `RTL_HAOS_BUILD` (auto-populated in HAOS/local deploy via `build.txt`).

### Diagnostics & field metadata
- **NEW:** Bridge diagnostics sensor: `sys_rtl_433_version` (captures `rtl_433 -V` once at startup).
- **NEW:** Water/utility metadata mappings for additional total fields (e.g. `total_m3`, `total_l`, `consumption_at_set_date_m3`).
- **NEW:** Expand `field_meta` coverage for common `rtl_433` fields (battery/pressure/wind/lux/UV/air quality/power/energy + common aliases like `*_dB`, multi-probe `temperature_#_*`, `humidity_#`).
- **CHANGED:** Home Assistant MQTT discovery publishes richer units/device_class/icons for these fields. Existing installs may need a discovery refresh (clear retained discovery topics / NUKE) to see updated metadata.

### Command building & compatibility
- **CHANGED:** `protocols` in `rtl_config` now accepts either a list or a comma/space-separated string (as commonly returned by HA add-on UI).
- **CHANGED:** `rtl_433` command creation is centralized and always forces `-F json -M level` so RTL-HAOS can parse messages (non-JSON lines are ignored).
- **NEW:** Startup logs print the full `rtl_433` command line per radio (`rtl_433 cmd ...`) for copy/paste troubleshooting.
- **CHANGED:** Global passthrough (`RTL_433_ARGS` / `rtl_433_args`) now acts as a **global override**: any option present wins over per-radio settings/auto defaults, with a **WARNING per radio** and de-duplicated flags.

### Filtering
- **FIX:** `device_whitelist` now matches patterns against the decoded device's **ID**, **model**, and **type** (previously it only matched the cleaned ID), restoring documented model-based whitelisting behavior.
- **DOCS:** Clarify whitelist/blacklist glob syntax (no regex) and add examples for model- and ID-based rules.

### Tests
- **NEW:** Unit tests for version handling and command building.
- **NEW:** Hardware-only smoke test for passthrough flags (skipped unless `RUN_HARDWARE_TESTS=1`).
- **NEW:** Unit tests to lock down `field_meta` mappings and verify discovery payloads use them.
- **NEW:** Optional fixture-driven guard test that flags unmapped/publishable fields from real `rtl_433` JSON captures (skips if no fixtures are present).
- **FIX:** Ensure `run.sh` is executable (repo health test stability).

## v1.1.14

### Utility meters: correct gas vs electric units
- **FIX:** Utility meters now publish **correct units and scaling** based on the detected commodity:
  - **Electric (ERT-SCM / SCMplus):** publishes **Energy (kWh)** and converts from the protocol’s hundredths (÷100).
  - **Gas (ERT-SCM / SCMplus):** publishes **Gas volume (ft³)** by default (raw counter, no scaling).
  
- **NEW:** Add-on option `gas_unit` to publish gas in your preferred unit:
  - `ft3` (default): publish the raw counter as **ft³**
  - `ccf`: publish **CCF** (billing units) by converting from ft³ (÷100)

### Other fixes
- **FIX:** Auto-rename duplicate RTL-SDR USB serial numbers (e.g. `00000001` → `00000001-1`) to prevent hardware map collisions and missing radios.
- **FIX:** Improve resilience when spawning RTL tooling (`rtl_433`, `rtl_eeprom`) by tolerating non-UTF8 output (prevents rare startup/runtime decode crashes).
- **FIX:** Improve Home Assistant MQTT discovery refresh when meter metadata arrives late (less need to “nuke” for unit/device_class corrections).
- **NEW:** Add metadata support for common volume fields (e.g., `volume_gal`, `volume_ft3`, `volume_m3`) so they publish with appropriate units/icons.
- **FIX:** Neptune-R900 water meters: publish `meter_reading` in **gallons** (model-aware unit override) for more accurate/default-friendly reporting.

### Migration from v1.1.13
- **Gas meters (ERT-SCM / SCMplus):** v1.1.14 publishes **raw ft³ totals** by default. If you were previously seeing “CCF-like” numbers in v1.1.13, your gas sensor value may appear to jump by ~**100×** after upgrading. This is expected.
  - If you prefer **CCF**, set `gas_unit: ccf` (or use a template sensor dividing by 100).
- **Electric meters (ERT-SCM / SCMplus):** v1.1.14 continues to publish **scaled kWh** (hundredths → kWh). Electric values should remain consistent.
- **Home Assistant discovery refresh:** if HA doesn’t immediately reflect updated unit/device_class, use the add-on “NUKE” cleanup (if provided) or clear retained discovery topics, then restart.
- **Multiple RTL-SDR dongles with duplicate serials:** duplicates may be renamed with a suffix (`SERIAL-1`, `SERIAL-2`). If you use manual `rtl_config`, update IDs to match startup logs.

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
