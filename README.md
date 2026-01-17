# RTL-HAOS: RTL-433 to Home Assistant Bridge

![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-MQTT-orange)
![License](https://img.shields.io/badge/license-MIT-green)

A "drop-in" bridge that turns one or more **RTL-SDR dongles** into Home Assistant-friendly sensors via MQTT.

Unlike standard `rtl_433` scripts, this project captures **detailed signal metrics** (RSSI, SNR, Noise) for every received packet, allowing you to troubleshoot interference and optimize antenna placement directly from Home Assistant.

It also functions as a **System Monitor**, reporting the host machine's health (CPU, RAM, Disk, Temp) and the live status of the radio dongle itself, giving you a complete view of your hardware's performance in one place.

See rtl_433 documentation for supported devices: https://github.com/merbanan/rtl_433

---

## ✨ Features

- **Auto Multi-Radio (plug-and-go):** If you leave `rtl_config` empty and the add-on detects multiple RTL-SDR dongles, it will automatically start **1–3** `rtl_433` instances (based on how many dongles you plug in).
  - **Zero-clutter UI:** the only auto-mode knob in the add-on UI is the **Region / Band Plan** dropdown: `rtl_auto_band_plan: auto|us|eu|world`.
  - **Sharing SDRs / reserving a dongle:** In auto mode, RTL-HAOS will use additional RTL-SDR dongles if they’re plugged in.
    If you need to keep a stick free for another add-on/app (ADS-B, another rtl_433 stack, etc.), switch to **manual mode** by defining `rtl_config` so RTL-HAOS only claims the dongle(s) you specify.
  - **Radio #1:** default 433.92 MHz (typical sensors)
  - **Radio #2:** region-aware high-band:
    - **EU/UK/EEA/CH:** 868 MHz
    - **US/CA/AU/NZ (and most others):** 915 MHz
    - If Home Assistant country is unknown, it will hop 868/915 on Radio #2
  - **Radio #3 (if present):** a regional hopper for “interesting” bands that **does not intentionally overlap** Radio 1/2.
  - Want full control of rates / hop intervals / exact freqs? Define `rtl_config` (manual mode) and you are responsible for the complete radio configuration.

- **Zero-Config Discovery:** Sensors appear automatically in Home Assistant (via MQTT Discovery) with correct units, icons, and friendly names.
- **Signal Diagnostics:** Reports **RSSI, SNR, and Noise Floor** for every device, making it easy to identify weak signals, plot coverage ranges, or hunt down interference sources.
- **Smart System Monitor:**
  - Reports Host CPU, RAM, Disk, and Temperature.
  - **Live Radio Status:** Shows `"Scanning..."`, `"Online"`, or error states like `"No Device Found"` / `"Error: USB Busy"` for each radio, grouped with the host device.
- **Native Graphing:** Environmental sensors use the correct `measurement` state class, and meter-like fields use `total_increasing`, so graphs and statistics in Home Assistant just work for temperatures, humidity, pressure, light, and utility counters.
- **Noise Reduction:**
  - **Data Averaging:** Buffers readings (e.g., every 30s) to prevent database bloat from sensors that spam updates every second.
  - **Filtering:** Built-in Whitelist and Blacklist support to ignore your neighbor's tire pressure sensors.
- **Advanced Data:**
  - **Dew Point:** Automatically calculated from Temp + Humidity sensors.
  - **Multi-Radio Support:** Run multiple dongles on different frequencies simultaneously.
  
- **Advanced rtl_433 passthrough:** Optionally pass arbitrary `rtl_433` flags and/or a full `rtl_433` config file (`-c`) globally or per radio (gain/AGC/ppm/tuner settings/decoder selection).
- **Stable version comparisons + richer display:** Base add-on version stays `X.Y.Z` for Supervisor, while logs/device info can show `vX.Y.Z+<build>`.
- **New diagnostics:** Bridge publishes the running `rtl_433` version as a diagnostic sensor (`rtl_433 Version`).

> **Note (multi-dongle setups):** If you plug in multiple RTL-SDR dongles and leave `rtl_config: []`, RTL-HAOS will start multiple radios automatically.
> To force RTL-HAOS to use only one specific stick (and leave others for other software), define `rtl_config` (manual mode).

---


## 📚 Documentation

- **Configuration**: [docs/CONFIG.md](docs/CONFIG.md)
- **MQTT topics & discovery**: [docs/MQTT.md](docs/MQTT.md)
- **Multi-radio setup**: [docs/MULTI_RADIO.md](docs/MULTI_RADIO.md)
- **Development & testing**: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)


## 🧩 How It Works

```mermaid
graph TD
    subgraph "RF Devices (Airwaves)"
        A(<b>Weather Station</b>) -->|433.92 MHz| D(<b>Antenna</b>)
        B(<b>Motion Sensor</b>) -->|315 MHz| D
        C(<b>Utility Meter</b>) -->|915 MHz| D
    end

    subgraph "Host (Raspberry Pi / Linux)"
        D(<b>RTL-SDR Dongle</b>) -->|USB Signal| E(<b>rtl_433 Binary</b>)
        E -->|Raw JSON| F("<b>RTL-HAOS Bridge</b><br/>(This Software)")

        subgraph "System Stats"
            H(<b>CPU/RAM</b>) --> F
            I(<b>Disk/Temp</b>) --> F
        end
    end

    %% MQTT Broker
    F -->|MQTT Discovery JSON + state topics| G("<b>MQTT Broker</b><br/>(External or HAOS Add-on)")

    subgraph "Home Assistant"
        G -->|MQTT Auto-Discovery| J(<b>Sensor Entities</b>)
        G -->|Diagnostic Data| K(<b>System Monitor</b>)
    end

    %% STYLING

    %% RTL Bridge (Orange)
    style F fill:#f96,stroke:#333,stroke-width:4px,color:black,rx:10,ry:10

    %% MQTT Broker (Blue)
    style G fill:#bbdefb,stroke:#0d47a1,stroke-width:4px,color:black,rx:10,ry:10

    %% Sensor Entities (Green)
    style J fill:#5fb,stroke:#333,stroke-width:2px,color:black,rx:10,ry:10

    %% System Monitor (Gray)
    style K fill:#cfd8dc,stroke:#333,stroke-width:2px,color:black,rx:10,ry:10

    %% Input Devices (White)
    style A fill:#fff,stroke:#333,stroke-width:2px,color:black,rx:5,ry:5
    style B fill:#fff,stroke:#333,stroke-width:2px,color:black,rx:5,ry:5
    style C fill:#fff,stroke:#333,stroke-width:2px,color:black,rx:5,ry:5
```

---
## 📸 Screenshots

### System Health & Entity View

| System Monitor | Entity View |
|---|---|
| ![System Monitor](https://github.com/user-attachments/assets/723a5454-4876-4f86-af86-a10b3bba516e) | ![Entity View](https://github.com/user-attachments/assets/04939cba-dfa0-44fb-bb33-2c50db6a13ad) |

### Signal Diagnosis (SNR, RSSI, Noise)

![SNR](https://github.com/user-attachments/assets/93a22bc7-aa6f-4f88-8bdf-276ecb7cf383)
![RSSI](https://github.com/user-attachments/assets/a1138265-e95d-41ec-a02b-93030a0e4824)
![Noise Floor](https://github.com/user-attachments/assets/1a262af2-2273-40ce-9e9a-c5baac6ded78)

_The signal boost between 8:00 AM and 5:00 PM is due to the AcuRite 5-in-1 internal supercapacitor charging via solar panel._

### Historical Efficacy Diagnosis

![Historical Data](https://github.com/user-attachments/assets/267d057e-c6a8-4c96-9b92-6a268efd7a4a)


---

## 📂 Project Layout (high-level)

- `main.py` – Main entrypoint (starts radio manager(s), MQTT publishing, system monitoring).
- `rtl_manager.py` – Spawns/monitors `rtl_433` process(es) and handles multi-radio orchestration.
- `data_processor.py` – Handles buffering, averaging, and throttling.
- `mqtt_handler.py` – MQTT connection + Home Assistant MQTT Discovery publishing.
- `system_monitor.py` / `sensors_system.py` – Host stats + radio status publishing.
- `field_meta.py` – Field metadata (units, device class, icons, etc.).
- `utils.py` – Shared helpers (IDs, formatting, derived fields like dew point).
- `docs/` – Deeper documentation (config, MQTT, multi-radio, development/testing).
- `scripts/` – Developer helper scripts (test venv, fixture recording).
- `tests/` – Unit tests + opt-in integration/hardware tests.
- `docker-compose.yml` – Docker/Compose runtime.
- `repository.yaml` – Home Assistant add-on repository descriptor.


---

## 🛠️ Hardware Requirements

- **Host:** Raspberry Pi (3/4/5), Mini PC, Proxmox, or any Linux machine.
- **Radio:** RTL-SDR USB Dongle (RTL-SDR Blog V3, Nooelec, etc.).

---

## ⚙️ Configuration

Full configuration reference: **[docs/CONFIG.md](docs/CONFIG.md)**.

> **Note:** If you're using the **Home Assistant Add-on**, skip this section and go directly to [Installation](#-installation). Add-on configuration is done through the Home Assistant UI.

This section applies to **Docker** and **Native** installation methods only.

### Upgrade Notes

Upgrading from v1.1.14 (or earlier)?

- **Displayed version may include `+<build>`** (example: `v1.2.0-rc.2+046cc83`). This is *only* build metadata for logs/device info; the base add-on `version:` in `config.yaml` remains a SemVer base version (`X.Y.Z` or `X.Y.Z-PRERELEASE`) for Home Assistant Supervisor comparisons.
- **New optional rtl_433 passthrough knobs** are available (global env vars and per-radio fields) if you need manual gain/AGC/ppm/tuner settings or a full `rtl_433` config file.
- **Add-on now maps `/share`**, so you can drop `rtl_433` config files into your HAOS share and reference them from RTL-HAOS.

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

**rtl_433 passthrough (advanced tuning):**

Use these when you need manual `rtl_433` controls (gain/AGC/ppm/tuner settings) or want to supply a full `rtl_433` config file (`-c`).

```bash
# Global overrides applied to every rtl_433 invocation
# Any option set here overrides the same option set per-radio/auto defaults; RTL-HAOS logs a WARNING per radio.
RTL_433_ARGS='-g 40 -p 0'

# Provide a config file passed via -c
# - Docker/Native: relative to your working directory
# - HA add-on: prefer putting files in /share and referencing them (e.g. rtl_433.conf)
RTL_433_CONFIG_PATH='rtl_433.conf'

# Or supply inline config content (RTL-HAOS writes a temp file and passes it via -c)
RTL_433_CONFIG_INLINE=$'-g 25\n-R 104\n'

# Optional override for rtl_433 binary path/name
RTL_433_BIN='rtl_433'
```

Per-radio tuning is also supported via `rtl_config` (fields like `args`, `device`, `config_path`, `config_inline`, `bin`). If an option is present in `RTL_433_ARGS`, it **wins over** the same option set per-radio/defaults and RTL-HAOS will log a WARNING indicating the override. See **docs/CONFIG.md** for examples.

**Build metadata (optional):**

```bash
# Appended to the displayed version as SemVer build metadata: vX.Y.Z+BUILD
# (Does not change Supervisor update comparisons)
RTL_HAOS_BUILD='dev.local'
```

**Multi-Radio Setup:**

> **Note**: If you only have **one** RTL-SDR, no other radio configuration is needed.
> The bridge will automatically try to read the dongle's serial with `rtl_eeprom` and use that.
> If it cannot detect a serial, it falls back to device index `id = "0"`.

For multiple RTL-SDR dongles on different frequencies:

```bash
# Multiple USB radios
RTL_CONFIG='[{"name": "Weather Radio", "id": "101", "freq": "433.92M", "rate": "250k"}, {"name": "Utility Meter", "id": "102", "freq": "915M", "rate": "250k"}]'
```

**TCP Source Setup (rtl_tcp):**

You can also connect to a remote SDR source using `rtl_tcp` instead of a local USB dongle:

```bash
# TCP source (e.g., from Ultrafeeder or another rtl_tcp server)
RTL_CONFIG='[{"name": "Remote SDR", "tcp_host": "192.168.1.10", "tcp_port": 1234, "freq": "433.92M", "rate": "250k"}]'
```

When using TCP mode:
- No USB device is required (`--privileged` and `--device` flags are not needed)
- The `tcp_host` and `tcp_port` parameters specify the remote rtl_tcp server
- Default port is 1234 if `tcp_port` is not specified
- You can mix USB and TCP sources in the same configuration

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
See [.env.example](.env.example) for all available configuration options.

---

## 🚀 Installation

### Option A: Home Assistant Add-on

The easiest way to use rtl-haos with Home Assistant OS is as an add-on.

#### 1. Add the Repository

In Home Assistant:

1. Navigate to **Settings** → **Add-ons** → **Add-on Store**
2. Click the **⋮** menu (top right) → **Repositories**
3. Add this repository URL:
   ```
   https://github.com/jaronmcd/rtl-haos
   ```
4. Click **Add**

#### 2. Install the Add-on

1. Find "RTL-HAOS" in the add-on store
2. Click on it and select **Install**
3. Wait for the installation to complete

#### 3. Configure the Add-on

Go to the **Configuration** tab and set your options:

**Basic Configuration:**

```yaml
# MQTT Settings
mqtt_host: ""          # Leave blank to auto-use the Home Assistant MQTT service (or set to core-mosquitto / broker IP)
mqtt_user: your_mqtt_user
mqtt_pass: your_mqtt_password

# Bridge identity (keeps your HA device stable)
bridge_id: "42"
bridge_name: "rtl-haos-bridge"
```

> **Note:** If `mqtt_host` is left blank, the add-on will try to use Home Assistant's Mosquitto service.

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

# Multi-Radio Configuration (leave empty for auto-detection)
rtl_config:
  - name: Weather Radio # Friendly name
    id: "101" # RTL-SDR USB serial number
    freq: 433.92M # Frequency
    rate: 250k # Sample rate (optional)

  - name: Utility Meter
    id: "102"
    freq: 915M
    rate: 250k

  # rtl_tcp mode (network SDR): run rtl_tcp on another host and point RTL-HAOS at it.
  # You can use either `device: "rtl_tcp:HOST:PORT"` or the explicit tcp_host/tcp_port keys.
  - name: Remote SDR (rtl_tcp)
    freq: 433.92M
    rate: 250k
    device: "rtl_tcp:192.168.1.10:1234"
    # tcp_host: "192.168.1.10"
    # tcp_port: 1234

# Device Filtering
device_blacklist: # Block specific device patterns
  - "SimpliSafe*"
  - "EezTire*"
device_whitelist: [] # If set, only allow these patterns
```

**Note:** If `rtl_config` is empty (`rtl_config: []`), RTL-HAOS runs in **auto mode** and will attach to detected RTL-SDR dongles automatically. Define `rtl_config` to pin specific radios, run multiple radios, or to use `rtl_tcp`.

#### 4. Start the Add-on

1. Go to the **Info** tab
2. Enable **Start on boot** (recommended)
3. Click **Start**
4. Check the **Log** tab to verify it's running

---

### Option B: Docker

Once you have set up your configuration, you can run rtl-haos with Docker.

#### Run with Docker Compose

```bash
docker compose up -d
```

#### Or run with Docker directly

```bash
# Build the image
docker build -t rtl-haos .

# Run the container (USB mode)
docker run -d \
  --name rtl-haos \
  --restart unless-stopped \
  --privileged \
  --device /dev/bus/usb:/dev/bus/usb \
  --env-file .env \
  rtl-haos

# Run the container (TCP mode - no USB device needed)
docker run -d \
  --name rtl-haos \
  --restart unless-stopped \
  --env-file .env \
  rtl-haos
```

> **Note:** The `--privileged` and `--device` flags are required for USB access to the RTL-SDR dongle. When using TCP mode (rtl_tcp), these flags are not needed.

#### View logs

```bash
docker compose logs -f
# or
docker logs -f rtl-haos
```

---

### Option C: Native Installation

#### 1. System Dependencies

Install Python and the `rtl_433` binary.

```bash
# Debian / Ubuntu / Raspberry Pi OS
sudo apt update
sudo apt install -y rtl-sdr rtl-433 git python3 python3-pip curl
```

#### 2. Install uv (Python package manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 3. Install Dependencies

```bash
# Update your Shell
source ~/.bashrc
# From the rtl-haos directory
uv sync
```

---

## ▶️ Usage

MQTT topic details: **`docs/MQTT.md`**.

### Home Assistant Add-on

Once the add-on is running, sensors will automatically appear in Home Assistant via MQTT Discovery. Check the add-on logs for status:

1. Navigate to **Settings** → **Add-ons** → **RTL-HAOS**
2. Click on the **Log** tab

### Docker

```bash
docker compose up -d
docker compose logs -f
```

### Native

```bash
cd rtl-haos
uv run python main.py
```

**Expected Output:**

```text
[STARTUP] Connecting to MQTT Broker at 192.168.1.100...
[MQTT] Connected Successfully.
[RTL] Manager started for Weather Radio. Monitoring...
 -> TX RaspberryPi (b827eb...) [radio_status_0]: Scanning...
 -> TX RaspberryPi (b827eb...) [radio_status_0]: Online
 -> TX Acurite-5n1 (1234) [temperature]: 72.3
```

> **Note:** It may take a few minutes for the system to receive its first radio transmission.

---


## 🧨 Maintenance: Cleanup & Radio Restart

RTL-HAOS exposes two maintenance buttons on the **Bridge** device to help with stale entities or a stuck radio process.

### 🧹 Delete Entities (Press 5x)

If you change batteries or remove devices, old entities may linger in Home Assistant. This cleanup tool clears the **MQTT Discovery configs** RTL-HAOS created.

1. Navigate to **Settings** → **Devices**
2. Open your Bridge device (named like `rtl-haos-bridge (xxxxxxxxxxxx)`)
3. Find the button **"Delete Entities (Press 5x)"**
4. Press it **5 times within 5 seconds**

What happens?
- RTL-HAOS scans retained Home Assistant discovery topics (`homeassistant/+/+/config`) for devices whose `manufacturer` contains `"rtl-haos"`.
- It publishes empty retained payloads to remove those discovery configs.
- Home Assistant removes the devices/entities almost immediately.
- Valid devices reappear automatically the next time they transmit data (discovery is republished on the next reading).

⚠️ Note: This scan matches on `manufacturer: rtl-haos`, so if you run **multiple RTL-HAOS bridges on the same broker**, it can remove discovery entries for *all* of them.

### 🔁 Restart Radios

If `rtl_433` gets wedged (USB hiccup, driver weirdness, no packets flowing), you can restart the radio processes without rebooting the host/add-on.

1. Navigate to **Settings** → **Devices** → your Bridge device
2. Press **"Restart Radios"**

What happens?
- RTL-HAOS terminates the running `rtl_433` process(es).
- The radio manager automatically re-launches them.
- The Radio Status entity will briefly show **"Rebooting..."**, then return to normal scanning/online behavior.

Notes:
- **Delete Entities** clears discovery/entities; it does *not* restart anything.
- **Restart Radios** restarts `rtl_433`; it does *not* restart Home Assistant or the container/add-on.


---

### 🪫 Battery Low (battery_ok)

If `rtl_433` reports a `battery_ok` field for a device, RTL-HAOS publishes a Home Assistant
**Battery Low** `binary_sensor`:

- `battery_ok = 0` → **Battery Low = ON** (LOW)
- `battery_ok = 1` → **Battery Low = OFF** (OK)

**Battery clear delay:** `battery_ok_clear_after` controls when LOW clears:

- `0` clears LOW immediately on the next OK report
- `>0` clears LOW only after `battery_ok` has remained OK for that many seconds (helps prevent flapping)

> Note: Many devices report battery infrequently. Battery Low uses a long MQTT `expire_after`
> (24h minimum) so it won’t quickly flip to “unavailable” just because no new `battery_ok`
> value was included in recent packets.

## 🔧 Advanced: Multi-Radio Setup

If you plan to run multiple RTL-SDR dongles (e.g. 433 MHz + 915 MHz), you **must** give each dongle a unique serial number and then configure `rtl_config` to pin each radio to its frequency.

See [docs/MULTI_RADIO.md](docs/MULTI_RADIO.md) for the full, step-by-step EEPROM/serial guide and `status_id` tips.

---

## 🤖 Running as a Service

To keep the bridge running 24/7 using the native installation method, use `systemd`.

1.  **Create the service file:**

    ```bash
    sudo nano /etc/systemd/system/rtl-bridge.service
    ```

2.  **Paste the configuration** (Update paths to match your username!):

    ```ini
      [Unit]
      Description=RTL-HAOS MQTT Bridge
      # Wait for the network to have a valid IP address before starting
      Wants=network-online.target
      After=network-online.target

      [Service]
      Type=simple
      # CHANGE THIS to your username (e.g., pi, user, admin)
      User=pi
      # CHANGE THIS to your directory path
      WorkingDirectory=/home/pi/rtl-haos

      # Unbuffer output so logs show up immediately
      Environment=PYTHONUNBUFFERED=1

      # Wait 10 seconds before starting to ensure USB device is ready
      ExecStartPre=/bin/sleep 10

      # CHANGE THESE PATHS to match your virtual environment and script location
      ExecStart=/home/pi/rtl-haos/.venv/bin/python3 /home/pi/rtl-haos/main.py

      # Restart automatically if it crashes
      Restart=on-failure
      RestartSec=5
      # Infinite restart attempts (do not stop trying)
      StartLimitIntervalSec=0

      [Install]
      WantedBy=multi-user.target
    ```

3.  **Enable and Start:**

    ```bash
      sudo systemctl daemon-reload
      sudo systemctl enable rtl-bridge.service
      sudo systemctl start rtl-bridge.service
    ```

4.  **Check Status:**
    ```bash
      systemctl status rtl-bridge.service
    ```

---
## ❓ Troubleshooting

- **Docker/Compose build fails with:** `exec /bin/ash: exec format error`
  - **Cause:** CPU architecture mismatch (most commonly an `amd64` base image being built/run on Raspberry Pi `arm64/armv7`). This is not an `apk add` dependency problem.
  - **Quick checks:**
    ```bash
    uname -m
    docker info --format 'arch={{.Architecture}} os={{.OperatingSystem}}'
    env | grep -E '^DOCKER_DEFAULT_PLATFORM=' || true
    docker compose config | grep -nE '^\s*platform:' || true
    ```
  - **Fix (recommended):** do not force `linux/amd64`, then rebuild cleanly:
    ```bash
    unset DOCKER_DEFAULT_PLATFORM || true
    docker compose build --no-cache --pull
    docker compose up
    ```
  - **If you must pin the platform explicitly:**
    - Raspberry Pi OS 64-bit (Pi 3/4/5): `linux/arm64`
    - Raspberry Pi OS 32-bit: `linux/arm/v7`
    Example:
    ```yaml
    services:
      rtl-haos:
        platform: linux/arm64
    ```
  - **Note on emulation (QEMU/binfmt):** you *can* run `amd64` on ARM with emulation, but it is slower and not recommended for SDR workloads. Prefer native ARM images.

- **"Service Fails to Start" (Exit Code Error)**
  - Check your username in the service file. If your terminal says `user@hostname`, your `User=` line must be `user`, not `pi`.
  - Verify paths. Run `ls /home/YOUR_USER/rtl-haos` to make sure the folder exists.
  - Check the logs: `journalctl -u rtl-bridge.service -b`

- **"No Device Found" in Logs**
  - The script cannot see your USB stick.
  - Run `lsusb` to verify it is plugged in.
  - Ensure you are not running another instance of `rtl_433` in the background (USB busy).
  - If running via `systemd`, the `ExecStartPre=/bin/sleep 10` line in the service file usually fixes this by waiting for the USB to wake up on reboot.
  - If running via Docker/Compose, ensure USB passthrough is enabled:
    - Compose: `privileged: true` and `/dev/bus/usb:/dev/bus/usb`
    - Or docker CLI: `--privileged --device /dev/bus/usb:/dev/bus/usb`
  - Hard reset your hardware or virtual machine (USB can wedge).

- **"Kernel driver is active" Error**
  - Linux loaded the default TV tuner driver. You need to blacklist it:
    ```bash
    echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/blacklist-rtl.conf
    sudo reboot
    ```

- **Sensors updates are slow**
  - Check `RTL_THROTTLE_INTERVAL`. Default is 30 seconds. Set to 0 for instant updates (not recommended for noisy environments).

- **Ghost Devices won't delete**
  - Use **Delete Entities (Press 5x)** (see **Maintenance: Cleanup & Radio Restart** above).
  - If that still fails, use an MQTT explorer and delete the *retained* Home Assistant discovery topics created by RTL-HAOS:
    - `homeassistant/sensor/*/config`
    - `homeassistant/button/*/config`
    Look for discovery payloads where `device.manufacturer` is `"rtl-haos"`.
