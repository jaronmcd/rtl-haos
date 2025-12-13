# RTL-HAOS: RTL-433 to Home Assistant Bridge

![Python Version](https://img.shields.io/badge/python-3.7%2B-blue)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-MQTT-orange)
![License](https://img.shields.io/badge/license-MIT-green)

A "drop-in" bridge that turns one or more **RTL-SDR dongles** into Home Assistant-friendly sensors via MQTT.

Unlike standard `rtl_433` scripts, this project captures **detailed signal metrics** (RSSI, SNR, Noise) for every received packet, allowing you to troubleshoot interference and optimize antenna placement directly from Home Assistant.

It also functions as a **System Monitor**, reporting the host machine's health (CPU, RAM, Disk, Temp) and the live status of the radio dongle itself, giving you a complete view of your hardware's performance in one place.

See rtl_433 documentation for supported devices: https://github.com/merbanan/rtl_433

---

## ✨ Features

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

---

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
- `mqtt_handler.py` – MQTT connection + Home Assistant MQTT Discovery publishing.
- `system_monitor.py` / `sensors_system.py` – Host stats + radio status publishing.
- `field_meta.py` – Field metadata (units, device_class/state_class, icons, etc.).
- `utils.py` – Shared helpers (IDs, formatting, derived fields like dew point, etc.).
- `docker-compose.yml` – Docker/Compose runtime.
- `repository.yaml` – Home Assistant add-on repository descriptor.

> Note: The repo may also contain legacy scripts/config templates (e.g., `rtl_mqtt_bridge.py`, `config.example.py`). If they’re kept, document them as legacy; otherwise remove them to avoid user confusion.


---

## 🛠️ Hardware Requirements

- **Host:** Raspberry Pi (3/4/5), Mini PC, Proxmox, or any Linux machine.
- **Radio:** RTL-SDR USB Dongle (RTL-SDR Blog V3, Nooelec, etc.).

---

## ⚙️ Configuration

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
MQTT_HOST=192.168.1.100
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
# Multiple radios (id should match dongle serial)
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
mqtt_host: "" # Leave blank to auto-use HA MQTT service (mqtt:want). Or set to "core-mosquitto" / your broker IP/hostname.
mqtt_user: your_mqtt_user
mqtt_pass: your_mqtt_password

bridge_name: "rtl-haos-bridge"        # unique ID for system metrics device

rtl_default_freq: "433.92M"           # or "433.92M, 315M, 915M"
rtl_default_hop_interval: 60          # only used when multiple freqs set
```

> **Note:** The add-on will automatically use the Home Assistant MQTT service if available and `mqtt_host` is left blank.

**Advanced Configuration (Optional, default values shown below):**

```yaml
# Publishing Settings
rtl_expire_after: 600 # Seconds before sensor marked unavailable
rtl_throttle_interval: 30 # Seconds to buffer/average data (0 = realtime)
debug_raw_json: false # Print raw rtl_433 JSON for debugging

# Multi-Radio Configuration (leave empty for auto-detection)
rtl_config:
  - name: Weather Radio # Friendly name
    id: "101" # RTL-SDR serial number
    freq: 433.92M # Frequency
    rate: 250k # Sample rate (optional)
  - name: Utility Meter
    id: "102"
    freq: 915M
    rate: 250k

# Device Filtering
device_blacklist: # Block specific device patterns
  - "SimpliSafe*"
  - "EezTire*"
device_whitelist: [] # If set, only allow these patterns
```

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

# Run the container
docker run -d \
  --name rtl-haos \
  --restart unless-stopped \
  --privileged \
  --device /dev/bus/usb:/dev/bus/usb \
  --env-file .env \
  rtl-haos
```

> **Note:** The `--privileged` and `--device` flags are required for USB access to the RTL-SDR dongle.

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
# From the rtl-haos directory
uv sync
```

---

## ▶️ Usage

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


## 🧨 Maintenance: The "Nuke" Button

If you change batteries or remove devices, old entities may linger in Home Assistant. RTL-HAOS provides a cleanup tool.


1. Navigate to **Settings** → **Devices** → **RTL-HAOS Bridge**
2. Find the button **"Delete Entities (Press 5x)".**
3. Press it **5 times within 5 seconds.**
   
What happens?
  -  The bridge scans the MQTT broker for all entities it created.
  -  It sends empty payloads to remove the "Discovery" configs.
  -  Home Assistant instantly removes the devices.
  -  Valid devices will reappear automatically the next time they transmit data.

    

    

---

## 🔧 Advanced: Multi-Radio Setup (Critical)

If you plan to use multiple RTL-SDR dongles (e.g., one for 433MHz and one for 915MHz), you **must** assign them unique serial numbers. By default, most dongles share the serial `00000001`, which causes conflicts where the system swaps "Radio A" and "Radio B" after a reboot.

### ⚠️ Step 1: Safety First (Backup EEPROM)

Before modifying your hardware, it is good practice to dump the current EEPROM image. This allows you to restore the dongle if something goes wrong.

1.  Stop any running services (e.g., `sudo systemctl stop rtl-bridge`).
2.  Plug in **ONE** dongle.
3.  Run the backup command:
    ```bash
    rtl_eeprom -r original_backup.bin
    ```
    _This saves a binary file `original_backup.bin` to your current folder._

### Step 2: Set New Serial Number

1.  With only one dongle plugged in, run:
    ```bash
    rtl_eeprom -s 101
    ```
    _(Replace `101` with your desired ID, e.g., 102, 103)._
2.  **Unplug and Replug** the dongle to apply the change.
3.  Verify the new serial:
    ```bash
    rtl_test
    # Output should show: SN: 101
    ```
4.  Repeat for your other dongles (one at a time).

> **Restoration:** If you ever need to restore the backup, use: `rtl_eeprom -w original_backup.bin`

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
- **"Service Fails to Start" (Exit Code Error)**
  - Check your username in the service file. If your terminal says user@hostname, your User= line must be user, not pi
  - Verify paths. Run ls /home/YOUR_USER/rtl-haos to make sure the folder exists.
  - Check the logs: journalctl -u rtl-bridge.service -b
- **"No Device Found" in Logs:**
  - The script cannot see your USB stick.
  - Run `lsusb` to verify it is plugged in.
  - Ensure you are not running another instance of `rtl_433` in the background.
  - The ExecStartPre=/bin/sleep 10 line in the service file usually fixes this by waiting for the USB to wake up on reboot.
  - Hard reset your Hardware or Virtual Machine.
- **"Kernel driver is active" Error:**
  - Linux loaded the default TV tuner driver. You need to blacklist it.
  - Run: `echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/blacklist-rtl.conf` and reboot.
- **Sensors updates are slow:**
  - Check `RTL_THROTTLE_INTERVAL`. Default is 30 seconds. Set to 0 for instant updates (not recommended for noisy environments).
- **Ghost Devices won't delete:**
  - Use the "Nuke" button (press 5x quickly).
  - If that fails, use an MQTT explorer to delete topics under `homeassistant/sensor/rtl433_....`