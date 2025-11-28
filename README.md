# RTL-HAOS: RTL-433 to Home Assistant Bridge

![Python Version](https://img.shields.io/badge/python-3.7%2B-blue)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-MQTT-orange)
![License](https://img.shields.io/badge/license-MIT-green)

A "drop-in" bridge that turns one or more **RTL-SDR dongles** into Home Assistant-friendly sensors via MQTT. 

Unlike standard `rtl_433` scripts, this project captures **detailed signal metrics** (RSSI, SNR, Noise) for every received packet, allowing you to troubleshoot interference and optimize antenna placement directly from Home Assistant. 

It also functions as a **System Monitor**, reporting the host machine's health (CPU, RAM, Disk, Temp) and the live status of the radio dongle itself, giving you a complete view of your hardware's performance in one place.

---

## ✨ Features

* **Zero-Config Discovery:** Sensors appear automatically in Home Assistant (via MQTT Discovery) with correct units, icons, and friendly names.
* **Signal Diagnostics:** Reports **RSSI, SNR, and Noise Floor** for every device, making it easy to identify weak signals, plot coverage ranges, or hunt down interference sources.
* **Smart System Monitor:**
    * Reports Host CPU, RAM, Disk, and Temperature.
    * **Live Radio Status:** Reports if the SDR is "Online," "Scanning," or "Disconnected" (grouped with the host device).
* **Native Graphing:** All sensors utilize Home Assistant's `measurement` state class, enabling automatic, long-term historical graphing of temperature, humidity, and system resources.
* **Noise Reduction:**
    * **Data Averaging:** Buffers readings (e.g., every 30s) to prevent database bloat from sensors that spam updates every second.
    * **Filtering:** Built-in Whitelist and Blacklist support to ignore your neighbor's tire pressure sensors.
* **Advanced Data:**
    * **Dew Point:** Automatically calculated from Temp + Humidity sensors.
    * **Multi-Radio Support:** Run multiple dongles on different frequencies simultaneously.

---

## 🧩 How It Works

```mermaid
graph TD
    subgraph "RF Devices (Airwaves)"
        A[Weather Station] -->|433.92 MHz| D[Antenna]
        B[Tire Sensor] -->|315 MHz| D
        C[Utility Meter] -->|915 MHz| D
    end

    subgraph "Host Machine (Raspberry Pi/Linux)"
        D[RTL-SDR Dongle] -->|USB Signal| E[rtl_433 Binary]
        E -->|Raw JSON| F("<b>RTL-HAOS Bridge</b><br/>(This Software)")
        
        subgraph "System Stats"
            H[CPU/RAM] --> F
            I[Disk/Temp] --> F
        end

        F -->|Filtered & Formatted JSON| G[MQTT Broker]
    end

    subgraph "Home Assistant"
        G -->|MQTT Auto-Discovery| J[Sensor Entities]
        G -->|Diagnostic Data| K[System Monitor]
    end
    
    style F fill:#f96,stroke:#333,stroke-width:2px,color:black
    style J fill:#5fb,stroke:#333,stroke-width:1px,color:black
```

---

## 📸 Screenshots

| Device View | System Monitor |
|:---:|:---:|
| *[Insert screenshot of a Weather Sensor in HA]* | *[Insert screenshot of the System/Radio Status device]* |

---

## 📂 Project Layout

* `rtl_mqtt_bridge.py`: Main entry point. Manages threads for `rtl_433`, buffering, and system stats.
* `config.py`: **User-Editable Settings** (Radios, Filters, MQTT).
* `mqtt_handler.py`: Handles MQTT connection and Home Assistant Auto-Discovery.
* `field_meta.py`: Definitions for icons, units, and device classes.
* `system_monitor.py`: Collects hardware metrics (CPU/RAM/Disk).

---

## 🛠️ Hardware Requirements

* **Host:** Raspberry Pi (3/4/5), Mini PC, or any Linux machine.
* **Radio:** RTL-SDR USB Dongle (RTL-SDR Blog V3, Nooelec, etc.).

---

## 🚀 Installation

### 1. System Dependencies
Install Python and the `rtl_433` binary.

```bash
# Debian / Ubuntu / Raspberry Pi OS
sudo apt update
sudo apt install -y rtl-433 git python3 python3-pip python3-venv libatlas-base-dev
```

> **⚠️ Important:** Ensure your user has permission to access the USB stick!
> If you haven't already, install the rtl-sdr udev rules:
> `sudo apt install rtl-sdr` (or download the rules manually). Unplug and replug your dongle after installing.

### 2. Clone & Setup
```bash
git clone [https://github.com/jaronmcd/rtl-haos.git](https://github.com/jaronmcd/rtl-haos.git)
cd rtl-haos

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python requirements
pip3 install -r requirements.txt
```

### 3. Configuration
Copy the example config and edit it.

```bash
cp config.example.py config.py
nano config.py
```

**Key Configuration Examples:**

```python
# --- MQTT ---
MQTT_SETTINGS = {
    "host": "192.168.1.100",
    "user": "mqtt_user",
    "pass": "password"
}

# --- MULTI-RADIO SETUP ---
# You can define multiple radios here.
RTL_CONFIG = [
    {"name": "Weather Radio", "id": "0", "freq": "433.92M", "rate": "250k"},
    {"name": "Utility Meter", "id": "1", "freq": "915M",    "rate": "250k"},
]

# --- FILTERING ---
# Ignore specific neighbors by ID or Model
DEVICE_BLACKLIST = [
    "SimpliSafe*",
    "EezTire*",
]
```

---

## ▶️ Usage

Run the bridge manually to test connection:

```bash
source venv/bin/activate
python3 rtl_mqtt_bridge.py
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

---

## 🤖 Running as a Service

To keep the bridge running 24/7, use `systemd`.

1.  **Create the service file:**
    ```bash
    sudo nano /etc/systemd/system/rtl-bridge.service
    ```

2.  **Paste the configuration** (Update paths to match your username!):
    ```ini
    [Unit]
    Description=RTL-HAOS MQTT Bridge
    After=network.target

    [Service]
    Type=simple
    User=pi
    # UPDATE THIS PATH
    WorkingDirectory=/home/pi/rtl-haos
    # UPDATE THIS PATH
    ExecStart=/home/pi/rtl-haos/venv/bin/python /home/pi/rtl-haos/rtl_mqtt_bridge.py
    Restart=always
    RestartSec=10

    [Install]
    WantedBy=multi-user.target
    ```

3.  **Enable and Start:**
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl enable rtl-bridge.service
    sudo systemctl start rtl-bridge.service
    ```

---

## ❓ Troubleshooting

* **"No Device Found" in Logs:**
    * The script cannot see your USB stick. 
    * Run `lsusb` to verify it is plugged in.
    * Ensure you are not running another instance of `rtl_433` in the background.
* **"Kernel driver is active" Error:**
    * Linux loaded the default TV tuner driver. You need to blacklist it.
    * Run: `echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/blacklist-rtl.conf` and reboot.
