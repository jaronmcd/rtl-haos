# Configuration

This page summarizes the main configuration entry points for RTL-HAOS.

- **Home Assistant Add-on users:** configure via **Settings → Add-ons → RTL-HAOS → Configuration**.
- **Developers / standalone runs:** see `.env.example` for environment variable configuration.
- **Full schema:** see `config.yaml` (authoritative list of all options and defaults).

---

## Home Assistant Add-on

In Home Assistant: **Settings → Add-ons → RTL-HAOS → Configuration**.

### Common options

```yaml
# MQTT
mqtt_host: core-mosquitto
mqtt_port: 1883
mqtt_user: ""
mqtt_pass: ""
mqtt_topic_prefix: rtl_433

# Logging
log_level: INFO
```

### Utility meters (gas + electric)

RTL-HAOS supports Itron-style utility meters (e.g., `ERT-SCM`, `SCMplus`) and publishes Home Assistant MQTT discovery entities for totals.

**Electric meters**
- Published as **Energy (kWh)**.
- Values are scaled from **hundredths of kWh → kWh** (÷100) when the meter is identified as electric.

**Gas meters**
- Published as **Gas (ft³)** by default (**raw** totals).
- Optional: publish in **CCF** (hundred cubic feet) by setting:

```yaml
gas_unit: ft3   # default
# gas_unit: ccf # optional (publishes totals in CCF by dividing ft³ by 100)
```

> **Upgrade note (v1.1.13 → v1.1.14):** gas totals may appear to increase by ~100× compared to v1.1.13 if you were previously seeing CCF-like values while labeled as ft³. This is expected when switching to raw ft³. See `CHANGELOG.md` → v1.1.14 → “Migration from v1.1.13”.

### Auto-config vs manual `rtl_config`

Most users can leave RTL in auto mode:

```yaml
rtl_auto: true
rtl_auto_frequency: 915000000
rtl_auto_sample_rate: 1024000
rtl_auto_gain: 0
```

If you want full control (multiple radios, fixed protocols, hopping, etc.), set `rtl_config` explicitly. The full shape and defaults are defined in `config.yaml`.

Example (manual radio with protocol filter):

```yaml
rtl_config:
  - name: equascan
    freq: 868.95M
    rate: 250k
    # Optional: limit rtl_433 decoders via -R
    # Comma- or space-separated ints, e.g. "104,105".
    protocols: "104,105"
```




### Wireless M-Bus decryption (OMS/EN13757-4 AES-128)

Some Wireless M-Bus meters (especially OMS v4 C-mode devices) encrypt the application payload. In that case, rtl_433 may still detect the meter and produce a JSON line with a `data` field, but totals (e.g., cumulative volume) will be missing or nonsense.

RTL-HAOS can optionally invoke **wmbusmeters** as a decode helper. RTL-HAOS forwards the raw telegram `data` hex to wmbusmeters, which performs AES-128 decryption and produces structured JSON fields such as `total_m3`.

Enable the helper and define one or more meters:

```yaml
wmbusmeters_enabled: true
wmbusmeters_meters:
  - name: equascan_water
    id: "01249398"   # your meter ID (often 8 digits; pad with leading zeros if needed)
    key: "00020108010201660368056502670469"  # AES-128 key (32 hex chars)
    driver: auto     # optional; use a specific driver if you know it
```

Notes:
- Keys should be treated as sensitive. RTL-HAOS does not log keys.
- If `wmbusmeters_enabled` is true, RTL-HAOS will forward `model: Wireless-MBus` telegrams to wmbusmeters and will not publish rtl_433's raw/decrypted fields for those telegrams.
- HA discovery: `total_m3` is published with `device_class: water` and `state_class: total_increasing` when present.
### Advanced: full rtl_433 passthrough

RTL-HAOS can pass **arbitrary rtl_433 flags** and/or a full **rtl_433 config file** (same format as `rtl_433 -c`: one argument per line). This is the most flexible way to tune reception (gain/ppm/AGC), constrain decoders, or use tuner settings.

**Global passthrough & overrides (applies to all radios):**

`rtl_433_args` is applied to every `rtl_433` invocation. **Any option you set here overrides the same option coming from per-radio settings or auto defaults** (e.g., `-s` sample rate, `-g` gain, `-p` ppm, `-R` decoders, etc.).

When a global override replaces a per-radio/default value, RTL-HAOS logs a **WARNING per radio** so it’s obvious in the Home Assistant add-on logs (yellow). This is intentional: it makes it easy to configure multi-radio once, then temporarily apply a common tuning parameter to all radios for testing.


```yaml
# Extra flags appended to every rtl_433 invocation
rtl_433_args: '-g 40 -p 0 -t "direct_samp=1"'

# Optional: provide an rtl_433 config file via -c
# In the HA add-on, relative paths resolve under /share (e.g. /share/rtl_433.conf).
rtl_433_config_path: "rtl_433.conf"

# Or inline config content (RTL-HAOS writes it to /tmp and passes -c /tmp/...)
rtl_433_config_inline: |
  -g 40
  -p 0
  -R 104
  -R 105
```

**Global override example (force one sample rate for all radios):**

```yaml
rtl_433_args: "-s 2000k"
```

This will override the per-radio/auto `rate:` values for every radio, and you’ll see a WARNING per radio showing what was overridden.

**Per-radio passthrough (adds radio-specific flags):**

Per-radio fields (`args`, `device`, `config_path`, `config_inline`, `bin`) let you add radio-specific tuning. If a per-radio flag conflicts with an option present in `rtl_433_args`, **the global option wins** and RTL-HAOS will emit a WARNING indicating the override.

```yaml
rtl_config:
  - name: utility
    freq: 868.95M
    rate: 250k

    # Optional: override which RTL-SDR this radio uses (-d accepts index/serial/Soapy selectors)
    device: ":00000001"

    # Extra flags for this radio only
    args: '-g 25 -t "biastee=1"'

    # Optional: per-radio config file or inline config (-c). Takes precedence over rtl_433_config_* globals; a -c in rtl_433_args will override and warn.
    config_path: "utility.conf"
    # config_inline: |
    #   -g 25
    #   -R 104
```

Notes:
- RTL-HAOS requires **JSON output** to function; `-F json` is enforced. If you provide your own `-F`, RTL-HAOS will keep JSON enabled.
- The startup log prints the final `rtl_433` command line per radio (copy/paste friendly) after overrides and de-duplication.
- You can still use the simpler `protocols:` field for a quick `-R` filter.

### Device filtering

You can restrict which decoded devices become entities using whitelist/blacklist rules:

```yaml
rtl_whitelist:
  - "Acurite-5n1*"
  - "AmbientWeather*"
rtl_blacklist:
  - "EcoWitt-WH40*"
```

(Exact matching behavior is defined in code; see `config.yaml` for the option names.)

### Multiple RTL-SDR dongles with duplicate serials

If you have multiple RTL-SDRs that report the same USB serial (common with some dongles), RTL-HAOS may suffix duplicates (e.g., `00000001-1`, `00000001-2`) to keep them distinct.  
If you use manual `rtl_config` device IDs, make sure they match what the add-on logs show at startup.

---

## Environment variables (dev / standalone)

For non–Home Assistant usage or development runs, you can configure via environment variables. See `.env.example` for the complete list.

---
