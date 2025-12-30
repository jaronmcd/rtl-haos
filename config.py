# config.py
"""Project configuration.

This module supports two deployment modes:

1) Home Assistant Add-on
   - Reads /data/options.json (validated by config.yaml schema)
   - Mirrors keys into environment variables

2) Standalone / Docker / venv
   - Reads a .env file (see .env.example)

IMPORTANT:
- Some settings are intentionally NOT exposed in the HA add-on UI. Those can still
  be overridden via .env for standalone deployments.
"""

from __future__ import annotations

import json
import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


OPTIONS_PATH = "/data/options.json"


def _load_ha_options_into_env() -> None:
    """If running as a HA add-on, load options.json into env vars."""
    if not os.path.exists(OPTIONS_PATH):
        return

    try:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            options = json.load(f)

        for key, value in options.items():
            env_key = key.upper()
            if isinstance(value, (list, dict)):
                os.environ[env_key] = json.dumps(value)
            elif value is not None and str(value).strip():
                os.environ[env_key] = str(value)
            elif key == "mqtt_host":
                # Allow users to leave mqtt_host blank in the add-on UI and still connect.
                os.environ.setdefault("MQTT_HOST", "core-mosquitto")

        print("[CONFIG] Success! Loaded settings from Home Assistant.")
    except Exception as e:  # pragma: no cover
        print(f"[CONFIG] Error loading options: {e}")


_load_ha_options_into_env()


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- MQTT ---
    mqtt_host: str = Field(default="localhost")
    mqtt_port: int = Field(default=1883)
    mqtt_user: str = Field(default="")
    mqtt_pass: str = Field(default="")
    mqtt_keepalive: int = Field(default=0)

    # --- RTL-SDR / Radios ---
    rtl_config: list[dict] = Field(default_factory=list)

    # Standalone-only advanced defaults (NOT exposed in HA add-on UI).
    rtl_default_freq: str = Field(default="433.92M")
    rtl_default_hop_interval: int = Field(default=60)
    rtl_default_rate: str = Field(default="250k")

    # --- Auto multi-radio defaults (used when rtl_config is empty) ---
    # If True and >=2 dongles are detected, start 2 radios automatically.
    rtl_auto_multi: bool = Field(default=True)

    # How many radios to start in auto mode.
    # - 0 means "use detected count" (bounded by rtl_auto_hard_cap).
    # - >0 starts exactly that many (bounded by available dongles).
    rtl_auto_max_radios: int = Field(default=0)

    # Hard safety cap when rtl_auto_max_radios=0 (use detected count). Set higher if you really want more.
    rtl_auto_hard_cap: int = Field(default=3)

    # Secondary band plan (used for Radio #2 in auto multi-mode):
    #  - auto   : infer from HA country (if available), else hop 868/915
    #  - us     : 915M
    #  - eu     : 868M
    #  - world  : hop 868M,915M
    #  - custom : use rtl_auto_secondary_freq
    rtl_auto_band_plan: str = Field(default="auto")

    # Used only when rtl_auto_band_plan=custom. Example: "920M" or "868M,915M".
    # If left blank, we fall back to the 'auto' behavior.
    rtl_auto_secondary_freq: str = Field(default="")

    # Auto primary/secondary rates (freqs are chosen elsewhere)
    rtl_auto_primary_rate: str = Field(default="250k")
    rtl_auto_secondary_rate: str = Field(default="1024k")

    # Optional 3rd radio (if present) acts as a regional "hopper" to catch interesting devices
    # outside the primary/secondary bands.
    #
    # - If rtl_auto_hopper_freqs is empty, the hopper plan is derived from HA country:
    #     * EU/UK/EEA/CH: 915M,315M,345M
    #     * Else (US/CA/AU/NZ/etc): 315M,345M,868M
    # - If rtl_auto_hopper_freqs is set, it is used verbatim (comma-separated).
    rtl_auto_hopper_freqs: str = Field(default="")
    rtl_auto_hopper_hop_interval: int = Field(default=20)
    rtl_auto_hopper_rate: str = Field(default="1024k")

    # --- Bridge identity ---
    bridge_id: str = Field(default="42")
    bridge_name: str = Field(default="rtl-haos-bridge")

    rtl_show_timestamps: bool = Field(
        default=False,
        description="If True, shows 'Last: HH:MM:SS'. If False, shows 'Online'.",
    )

    verbose_transmissions: bool = Field(
        default=False,
        description="If True, logs every MQTT publish. If False, only logs summaries.",
    )

    # --- Device filtering ---
    skip_keys: list[str] = Field(default_factory=lambda: ["time", "protocol", "mod", "id"])
    device_blacklist: list[str] = Field(default_factory=lambda: ["SimpliSafe*", "EezTire*"])
    device_whitelist: list[str] = Field(default_factory=list)

    # --- Main vs diagnostic sensors ---
    main_sensors: list[str] = Field(
        default_factory=lambda: [
            "sys_device_count",
            "temperature",
            "temperature_C",
            "temperature_F",
            "dew_point",
            "humidity",
            "pressure_hpa",
            "pressure_inhg",
            "pressure_PSI",
            "co2",
            "mics_ratio",
            "mq2_ratio",
            "mag_uT",
            "geomag_index",
            "wind_avg_km_h",
            "wind_avg_mi_h",
            "wind_gust_km_h",
            "wind_gust_mi_h",
            "wind_dir_deg",
            "wind_dir",
            "rain_mm",
            "rain_in",
            "rain_rate_mm_h",
            "rain_rate_in_h",
            "lux",
            "uv",
            "strikes",
            "strike_distance",
            "storm_dist",
            "Consumption",
            "consumption",
            "consumption_data",
            "meter_reading",
            "volume_gal",
            "volume_ft3",
            "volume_m3",
            "moisture",
        ]
    )

    # --- Publishing / processing ---
    rtl_expire_after: int = Field(default=600)
    force_new_ids: bool = Field(default=False)
    debug_raw_json: bool = Field(default=False)
    rtl_throttle_interval: int = Field(default=30)

    # --- Utility meter display units ---
    # rtl_433 / rtlamr-style meters often report gas volume in cubic feet.
    # Some utilities (and some physical registers) show hundred cubic feet (CCF).
    #
    # Supported values:
    #   - ft3 : cubic feet (default)
    #   - ccf : hundred cubic feet
    gas_volume_unit: str = Field(
        default="ft3",
        description="Display unit for gas volume utility meters: ft3 (cubic feet) or ccf (hundred cubic feet).",
    )

    # --- Battery alert behavior (battery_ok -> Battery Low binary_sensor) ---
    # 0 disables latching and clears low immediately on the next OK.
    battery_ok_clear_after: int = Field(
        default=300,
        description="Seconds battery_ok must be OK before clearing a low alert (0 disables).",
    )

    @property
    def id_suffix(self) -> str:
        return "_v2" if self.force_new_ids else ""


settings = Settings()

# --- Export convenience constants (existing code uses module-level names) ---
BRIDGE_ID = settings.bridge_id
BRIDGE_NAME = settings.bridge_name

MQTT_SETTINGS = {
    "host": settings.mqtt_host,
    "port": settings.mqtt_port,
    "user": settings.mqtt_user,
    "pass": settings.mqtt_pass,
    "keepalive": settings.mqtt_keepalive,
}

RTL_CONFIG = settings.rtl_config

# Standalone-only defaults
RTL_DEFAULT_FREQ = settings.rtl_default_freq
RTL_DEFAULT_HOP_INTERVAL = settings.rtl_default_hop_interval
RTL_DEFAULT_RATE = settings.rtl_default_rate

# Auto multi-radio
RTL_AUTO_MULTI = settings.rtl_auto_multi
RTL_AUTO_MAX_RADIOS = settings.rtl_auto_max_radios
RTL_AUTO_HARD_CAP = settings.rtl_auto_hard_cap
RTL_AUTO_BAND_PLAN = settings.rtl_auto_band_plan
RTL_AUTO_SECONDARY_FREQ = settings.rtl_auto_secondary_freq
RTL_AUTO_PRIMARY_RATE = settings.rtl_auto_primary_rate
RTL_AUTO_SECONDARY_RATE = settings.rtl_auto_secondary_rate
RTL_AUTO_HOPPER_FREQS = settings.rtl_auto_hopper_freqs
RTL_AUTO_HOPPER_HOP_INTERVAL = settings.rtl_auto_hopper_hop_interval
RTL_AUTO_HOPPER_RATE = settings.rtl_auto_hopper_rate

SKIP_KEYS = settings.skip_keys
DEVICE_BLACKLIST = settings.device_blacklist
DEVICE_WHITELIST = settings.device_whitelist
MAIN_SENSORS = settings.main_sensors

RTL_EXPIRE_AFTER = settings.rtl_expire_after
FORCE_NEW_IDS = settings.force_new_ids
ID_SUFFIX = settings.id_suffix

DEBUG_RAW_JSON = settings.debug_raw_json
RTL_THROTTLE_INTERVAL = settings.rtl_throttle_interval
RTL_SHOW_TIMESTAMPS = settings.rtl_show_timestamps

VERBOSE_TRANSMISSIONS = settings.verbose_transmissions

# Utility meters
GAS_VOLUME_UNIT = settings.gas_volume_unit

# Battery behavior
BATTERY_OK_CLEAR_AFTER = settings.battery_ok_clear_after
