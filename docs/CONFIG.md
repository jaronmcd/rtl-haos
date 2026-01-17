# Configuration

This page summarizes the main configuration entry points for RTL-HAOS.

- **Home Assistant Add-on users:** configure via **Settings -> Add-ons -> RTL-HAOS -> Configuration**.
- **Docker / standalone / development:** configure via `.env` (see `.env.example`).
- **Authoritative list of add-on options + defaults:** `config.yaml`.

---

## Home Assistant Add-on

Open **Settings -> Add-ons -> RTL-HAOS -> Configuration** and edit the YAML.

### Minimal configuration

```yaml
# MQTT
# - `mqtt_host` defaults to `core-mosquitto`.
# - If you run an external broker, set its IP/hostname.
mqtt_host: core-mosquitto
mqtt_port: 1883
mqtt_user: ""
mqtt_pass: ""

# Bridge identity (keeps your Home Assistant device stable)
bridge_id: "42"
bridge_name: "rtl-haos-bridge"
```

### Common options

```yaml
# Publishing behavior
rtl_expire_after: 600         # seconds before an entity is marked unavailable
rtl_throttle_interval: 30     # seconds to buffer/average updates (0 = realtime)
rtl_show_timestamps: false    # if true, show last-seen timestamp in entity state
verbose_transmissions: false  # if true, log every MQTT publish

debug_raw_json: false         # if true, print raw rtl_433 JSON lines

# Utility meters (gas)
gas_unit: ft3                 # ft3 (default) or ccf

# Battery alert behavior (battery_ok -> Battery Low)
battery_ok_clear_after: 300   # seconds battery_ok must be OK before clearing a low alert (0 disables)
```

### Auto mode vs manual rtl_config

- If `rtl_config` is empty (`rtl_config: []`), RTL-HAOS runs in **auto mode** and will start 1-3 radios depending on how many RTL-SDR dongles are detected.
- The only add-on UI knob that affects auto mode is `rtl_auto_band_plan`:

```yaml
rtl_auto_band_plan: auto  # one of: auto | us | eu | world
```

If you want full control (pin a specific stick, run multiple fixed radios, hop frequencies, or use rtl_tcp), define `rtl_config`.

### Manual rtl_config examples

#### USB RTL-SDR (pinned by USB serial)

```yaml
rtl_config:
  - name: "Weather"
    id: "101"        # RTL-SDR USB serial
    freq: 433.92M
    rate: 250k
```

#### Multi-frequency hopping

```yaml
rtl_config:
  - name: "High band hopper"
    id: "102"
    freq: "868M,915M"
    hop_interval: 15
    rate: 1024k
```

#### rtl_tcp (network SDR)

If your RTL-SDR is plugged into another machine (for example, your desktop PC), you can run `rtl_tcp` there and have RTL-HAOS connect over the network.

You can use either:
- `device: "rtl_tcp:HOST:PORT"` (works even without `tcp_host/tcp_port` fields), or
- the explicit `tcp_host` and `tcp_port` fields.

```yaml
rtl_config:
  - name: "Remote SDR"
    freq: 433.92M
    rate: 250k
    device: "rtl_tcp:192.168.1.10:1234"
    # tcp_host: "192.168.1.10"
    # tcp_port: 1234
```

### Optional protocol filter (-R)

You can constrain rtl_433 decoders per radio:

```yaml
rtl_config:
  - name: "Utility"
    freq: 868.95M
    rate: 250k
    protocols: "104,105"
```

### Advanced rtl_433 passthrough

RTL-HAOS can pass arbitrary `rtl_433` flags and/or a full `rtl_433` config file.

```yaml
# Global (applies to all radios)
rtl_433_args: '-g 40 -p 0'
rtl_433_config_path: "rtl_433.conf"     # under /share when running as an add-on
# rtl_433_config_inline: |
#   -g 40
#   -p 0

# Per radio
rtl_config:
  - name: "Utility"
    freq: 868.95M
    rate: 250k
    args: '-g 25'
    # device: ":00000001"               # explicit USB selector
    # config_path: "utility.conf"
    # config_inline: |
    #   -R 104
```

Notes:
- RTL-HAOS enforces JSON output (`-F json`) so it can parse data.
- If a setting is specified both per-radio and in `rtl_433_args`, the global value takes precedence and RTL-HAOS logs a warning.

### Device filtering

You can suppress unwanted devices using wildcard patterns.

- Patterns use shell-style glob matching (`fnmatch`): `*`, `?`, and `[]`.
- Matching is case-insensitive.
- Patterns are matched against the decoded device’s `id`, `model`, and `type` fields.

Rules:
- `device_blacklist` always blocks matching devices.
- If `device_whitelist` is non-empty, only matching devices are allowed.

```yaml
device_blacklist:
  - "SimpliSafe*"
  - "EezTire*"

device_whitelist: []  # if set non-empty, only matching devices are allowed
# device_whitelist:
#   - "Acurite-5n1*"
#   - "AmbientWeather*"

```

---

## Docker / standalone / development

For Docker/standalone runs, use `.env` (see `.env.example`). The add-on UI schema does not apply in this mode.

Common env vars:
- `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`
- `RTL_CONFIG` (JSON list of radio dicts)
- `RTL_433_ARGS`, `RTL_433_BIN`, `RTL_433_CONFIG_PATH`, `RTL_433_CONFIG_INLINE`

Example `RTL_CONFIG` using rtl_tcp:

```bash
RTL_CONFIG='[{"name":"Remote SDR","tcp_host":"192.168.1.10","tcp_port":1234,"freq":"433.92M","rate":"250k"}]'
```
