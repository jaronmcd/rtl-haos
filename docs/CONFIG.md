# Configuration

This page summarizes all configuration entry points.

- Full add-on schema: `config.yaml`
- Full env var list: `.env.example`

---

## Home Assistant Add-on

In Home Assistant: **Settings → Add-ons → RTL-HAOS → Configuration**.

**Basic Configuration:**

```yaml
# MQTT Settings
mqtt_host: core-mosquitto  # Recommended for HAOS (blank also falls back to core-mosquitto)
mqtt_user: your_mqtt_user
mqtt_pass: your_mqtt_password

# Bridge identity (keeps your HA device stable)
bridge_id: "42"
bridge_name: "rtl-haos-bridge"
```

> **Note:** If `mqtt_host` is blank, RTL-HAOS defaults to `core-mosquitto`.

**Advanced Configuration (Optional, default values shown below):**

```yaml
# Publishing Settings
rtl_expire_after: 600 # Seconds before sensor marked unavailable
rtl_throttle_interval: 30 # Seconds to buffer/average data (0 = realtime)
debug_raw_json: false # Print raw rtl_433 JSON for debugging

# Battery alert behavior (battery_ok -> Battery Low binary_sensor)
# 0 clears immediately on next OK
battery_ok_clear_after: 300
# Note: Battery Low uses a long MQTT expire_after (24h+) to avoid going 'unavailable' for devices that report battery infrequently.

# Multi-Radio Configuration
#
# Leave rtl_config empty for Auto Multi-Radio (plug-and-go).
rtl_config: []

# Region preset (dropdown in UI) used by Auto Multi-Radio for Radio #2
# auto = use Home Assistant country when available
rtl_auto_band_plan: auto     # auto|us|eu|world

# Device Filtering
device_blacklist: # Block specific device patterns
  - "SimpliSafe*"
  - "EezTire*"
device_whitelist: [] # If set, only allow these patterns
```

### Manual multi-radio example (rtl_config)

If you want full control, set `rtl_config` explicitly (manual mode disables auto mode):

```yaml
rtl_config:
  - name: Weather Radio
    id: "101"
    freq: 433.92M
    rate: 250k
  - name: Utility Meter
    id: "102"
    freq: 915M
    rate: 1024k
```

---

## Docker / Native (.env)

Standalone deployments read settings from a `.env` file.

> **Note:** If you're using the **Home Assistant Add-on**, skip this section and go directly to [Installation](#-installation). Add-on configuration is done through the Home Assistant UI.

This section applies to **Docker** and **Native** installation methods only.

### Setup

```bash
git clone https://github.com/jaronmcd/rtl-haos.git
cd rtl-haos

# Copy and edit the environment file
cp .env.example .env
nano .env
```

All configuration is done via environment variables in a `.env` file.

### Required Configuration

At minimum, you need to configure your MQTT broker connection:

```bash
# --- MQTT ---
MQTT_HOST="192.168.1.100"
MQTT_USER=mqtt_user
MQTT_PASS=password
```

### Advanced Configuration

**Multi-Radio Setup:**

> **Note**: If you only have **one** RTL-SDR, no other radio configuration is needed.
> The bridge will automatically try to read the dongle's serial with `rtl_eeprom` and use that.
> If it cannot detect a serial, it falls back to device index `id = "0"`.

For multiple RTL-SDR dongles on different frequencies:

```bash
# Multiple radios 
RTL_CONFIG='[{"name": "Weather Radio", "id": "101", "freq": "433.92M", "rate": "250k"}, {"name": "Utility Meter", "id": "102", "freq": "915M", "rate": "250k"}]'
```

**Device Filtering:**

Block or allow specific device patterns:

```bash
# Device filtering (block specific devices)
DEVICE_BLACKLIST='["SimpliSafe*", "EezTire*"]'

# Device filtering (allow only specific devices - optional)
DEVICE_WHITELIST='["Acurite-5n1*", "AmbientWeather*"]'
```
**Misc Configuration:**
```bash
# Toggle "Last: HH:MM:SS" vs "Online" in status
RTL_SHOW_TIMESTAMPS=false
# Print rtl_433 JSON output
DEBUG_RAW_JSON=true
```
See [.env.example](../.env.example) for all available configuration options.

---
