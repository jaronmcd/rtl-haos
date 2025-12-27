# Multi-Radio Setup

This page is duplicated from the README for easier linking.

## Plug-and-go Auto Multi-Radio

If you leave `rtl_config` empty (`rtl_config: []`), RTL-HAOS can automatically start multiple `rtl_433` instances when it detects multiple RTL-SDR dongles.

Auto mode is designed to be **zero-clutter**: you install the add-on, plug in 1–3 dongles, and it starts the right number of radios automatically.

The only auto-mode knob exposed in the add-on UI is the **Region / Band Plan** dropdown: `rtl_auto_band_plan` (default: `auto`).
  - EU/UK/EEA/CH -> 868 MHz
  - US/CA/AU/NZ and most others -> 915 MHz
  - If HA country is unknown -> hops 868/915

Band plan options:
- `auto`: use Home Assistant's country setting when available (recommended)
- `us`: force 915 MHz for Radio #2
- `eu`: force 868 MHz for Radio #2
- `world`: hop 868 + 915 on Radio #2 (best when country is unknown)

### Optional 3rd radio: regional hopper

If you have 3 dongles, **Radio #3 becomes a hopper** that scans “interesting” nearby bands for your region.

Auto hopper defaults:
- EU/UK/EEA/CH: hops 169.4, 868.95, 869.525, 915
- Else: hops 315, 345, 390, 868

The hopper will not intentionally overlap bands already covered by Radio #1/#2.

> Want full control of rates / hop intervals / exact freqs? Switch to **manual mode** by defining `rtl_config`. In manual mode, you are responsible for the complete radio configuration.

## Reserving a dongle (sharing SDRs with other apps)

Auto mode (`rtl_config: []`) is designed to “just work” — if multiple RTL-SDR dongles are detected, RTL-HAOS will start multiple radios automatically.

If you are **sharing SDR hardware** (another add-on/app needs one of the sticks), use **manual mode** so RTL-HAOS only claims the dongle(s) you want:

1. Give each dongle a stable serial (recommended, one dongle at a time):
   ```bash
   rtl_eeprom -s 101
   ```
2. In Home Assistant add-on config, define only the radios you want RTL-HAOS to run:
   ```yaml
   rtl_config:
     - name: Weather
       id: "101"
       freq: 433.92M
       rate: 250k
   ```
3. Leave the other dongle(s) unconfigured so they remain available for your other software.

If you see `"Error: USB Busy"` or `"No Device Found"` on a radio status entity, another process is likely holding that dongle — either stop the other service or switch RTL-HAOS to manual mode and point it at a different stick.

## Radio status entity naming

RTL-HAOS publishes a host-level **Radio Status** entity per radio (e.g. `radio_status_101`).

- By default, the suffix is derived from the radio's `id` (serial), then `index`, then the internal `slot`.
- If you want to keep legacy numbering like `radio_status_0` / `radio_status_1`, set `status_id` in each `rtl_config` entry.

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
