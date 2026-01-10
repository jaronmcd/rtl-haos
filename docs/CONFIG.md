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


### Advanced: full rtl_433 passthrough

### Drop-in `rtl_433.conf` support (default search paths)

`rtl_433` itself will automatically load the first `rtl_433.conf` it finds in its default
search locations (current directory, `XDG_CONFIG_HOME/rtl_433/rtl_433.conf`, then the
system config dir).

In Home Assistant add-on mode, RTL-HAOS sets `XDG_CONFIG_HOME=/config` for the `rtl_433`
subprocess (unless you already set `XDG_CONFIG_HOME`). That means you can simply create:

- `/config/rtl_433/rtl_433.conf`

…and `rtl_433` will pick it up automatically at startup, without needing to set `rtl_433_config_path`.
Anything set by RTL-HAOS on the command line (freq/rate/protocols/args) still applies and can override
values from the config file, just like running `rtl_433` normally.



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

### Gotchas when passing rtl_433 flags

A few common pitfalls when using `rtl_433_args` / per-radio `args`:

- **Don’t use flags that intentionally exit** (e.g. `-V` version, `-h` help). `rtl_433` will quit immediately and the add-on will restart it.
  - Similarly, using **finite-run flags** like `-T <seconds>` or `-n <samples>` will make `rtl_433` stop and get restarted.
- **Be careful enabling rtl_433’s built-in MQTT output** (`-F mqtt...`). RTL-HAOS already publishes to MQTT after parsing JSON, so turning on rtl_433 MQTT output usually results in **duplicate events** (two publishers).
- If you add additional `-F` outputs for debugging (e.g. `-F kv`, `-F csv:...`), make sure `-F json` is still present. RTL-HAOS will force JSON output for decoding.

RTL-HAOS will emit `WARNING: [VALIDATE] ...` messages at startup when it detects these patterns, but it will not block startup.


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


### Device ID strategy (avoid ID collisions)

By default, RTL-HAOS uses rtl_433's `id` field as the Home Assistant **device id**. For some protocols, that `id` can collide across different models (or reuse per-channel), which can cause **multiple physical devices to merge into one** in Home Assistant.

You can opt into a stronger device key:
**Home Assistant Add-on note:** Starting with RTL-HAOS 1.2.3, fresh installs default to `model_id_channel` in the add-on UI. Existing installs keep whatever is already saved in `/data/options.json` (typically `legacy`) until you change it.


```yaml
# Home Assistant add-on:
# - Fresh installs default to "model_id_channel" (reduces collisions)
# - Existing installs keep whatever is saved in /data/options.json (usually "legacy")
device_id_strategy: "model_id_channel"  # default for new installs
# device_id_strategy: "legacy"          # backwards-compatible (upgrade-safe)
# device_id_strategy: "model_id"        # model + id
# device_id_strategy: "template"        # advanced


# Used when device_id_strategy: "template"
device_id_template: "m{model}i{id}c{channel}"
```

Available template fields: `model`, `id`, `channel`, `subtype`, `protocol`, `type`.

> **Important:** Changing `device_id_strategy` changes the Home Assistant device id and therefore will create **new devices/entities** (the old ones won't automatically migrate).

### rtl_433 metadata options

RTL-HAOS enforces `-F json` and adds some metadata flags for convenience:

```yaml
rtl_meta_protocol: true      # adds '-M protocol' (modulation/protocol hints)
rtl_time_mode: "legacy"     # legacy|iso|utc (adds '-M time:iso' or '-M time:utc')
```

These fields are primarily used for debugging and for advanced device-id templates. RTL-HAOS still skips publishing `time`/`protocol` as standalone sensor entities by default.

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
