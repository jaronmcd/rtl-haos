# utils.py
"""
FILE: utils.py
DESCRIPTION:
  Shared helper functions used across the project.
  - clean_mac(): Sanitizes device IDs for MQTT topics.
  - calculate_dew_point(): Math formula to calculate Dew Point from Temp/Humidity.
  - get_system_mac(): Generates a unique ID for the bridge itself based on hardware.
  - validate_radio_config(): Checks for common configuration mistakes (Missing M, Missing ID, etc).
"""
import re
import math
import socket
import os
import json
import config

# Global cache
_SYSTEM_MAC = None

def get_system_mac():
    global _SYSTEM_MAC
    if _SYSTEM_MAC: 
        return _SYSTEM_MAC

    # 1. PREFERRED: Use Static ID from Config
    if config.BRIDGE_ID:
        _SYSTEM_MAC = config.BRIDGE_ID
        return _SYSTEM_MAC
    
    try:
        # 2. FALLBACK: Use Hostname (Dynamic on HAOS!)
        host_id = socket.gethostname()
        
        if not host_id:
            host_id = "rtl-bridge-default"
            
        _SYSTEM_MAC = host_id
        return _SYSTEM_MAC

    except Exception:
        return "rtl-bridge-error-id"

def clean_mac(mac):
    """Cleans up MAC/ID string for use in topic/unique IDs."""
    # Removes special characters to make it MQTT-safe
    cleaned = re.sub(r'[^A-Za-z0-9]', '', str(mac))
    return cleaned.lower() if cleaned else "unknown"

def calculate_dew_point(temp_c, humidity):
    """Calculates Dew Point (F) using Magnus Formula."""
    if temp_c is None or humidity is None:
        return None
    if humidity <= 0:
        return None 
    try:
        b = 17.62
        c = 243.12
        gamma = (b * temp_c / (c + temp_c)) + math.log(humidity / 100.0)
        dp_c = (c * gamma) / (b - gamma)
        return round(dp_c * 1.8 + 32, 1) # Return Fahrenheit
    except Exception:
        return None

def validate_radio_config(radio_conf):
    """
    Analyzes a radio configuration dictionary for common user errors.
    Returns a list of warning strings.
    """
    warnings = []
    
    # 1. Check Frequency for missing 'M'
    # rtl_433 defaults to Hz if no suffix is present.
    # 433.92 -> 433 Hz (Invalid). 433.92M -> 433,920,000 Hz (Valid).
    freq_str = str(radio_conf.get("freq", ""))
    frequencies = [f.strip() for f in freq_str.split(",")]
    
    for f in frequencies:
        # Regex: Matches pure numbers (int or float) with NO letters
        if re.match(r"^\d+(\.\d+)?$", f):
            val = float(f)
            # If value is < 1,000,000, it's almost certainly not Hz.
            if val < 1000000:
                warnings.append(
                    f"Frequency '{f}' has no suffix and will be read as Hz (impossible). "
                    f"Did you mean '{f}M'?"
                )

    # 2. Check Hop Interval vs Frequency Count
    # Hopping requires at least 2 frequencies.
    hop = int(radio_conf.get("hop_interval", 0))
    if hop > 0 and len(frequencies) < 2:
        warnings.append(
            f"Hop interval is set to {hop}s, but only 1 frequency provided ({freq_str}). "
            "Hopping will be ignored."
        )

    # 3. Check Sample Rate Suffix
    # 250 -> 250 Hz (Way too slow). 250k -> 250,000 Hz (Standard).
    rate = str(radio_conf.get("rate", ""))
    if re.match(r"^\d+$", rate):
        val = int(rate)
        if val < 1000000: 
            warnings.append(
                f"Sample rate '{rate}' has no suffix (e.g. 'k'). "
                f"Did you mean '{rate}k'?"
            )

    # 4. Check for Missing or Empty ID (NEW)
    # The system needs an ID to map the config to a specific USB stick.
    r_id = radio_conf.get("id")
    if r_id is None or str(r_id).strip() == "":
        warnings.append(
            "Configuration is missing a device 'id'. "
            "This radio may default to index 0 and conflict with others."
        )

    return warnings


def get_homeassistant_country_code() -> str | None:
    """Best-effort: infer Home Assistant country code (e.g. 'US', 'DE').

    - Add-on: reads /config/.storage/core.config
    - Standalone: optionally uses env var HOMEASSISTANT_COUNTRY / HA_COUNTRY
    Returns None if unknown.
    """
    # 1) Env override (works in any mode)
    for k in ("HOMEASSISTANT_COUNTRY", "HA_COUNTRY", "COUNTRY"):
        v = os.getenv(k)
        if v and str(v).strip():
            return str(v).strip().upper()

    # 2) Home Assistant storage (add-on)
    core_cfg = "/config/.storage/core.config"
    try:
        with open(core_cfg, "r", encoding="utf-8") as f:
            obj = json.load(f)
        # Typical structure: {"data": {"country": "US", ...}, ...}
        data = obj.get("data") if isinstance(obj, dict) else None
        if isinstance(data, dict):
            c = data.get("country")
            if c and str(c).strip():
                return str(c).strip().upper()
    except Exception:
        pass

    return None


_EU_868_COUNTRIES = {
    # EU + EEA + UK + CH (broadly 868 MHz ISM users)
    "AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE","IT",
    "LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE",
    "IS","LI","NO","CH","GB",
}


def choose_secondary_band_defaults(
    plan: str = "auto",
    country_code: str | None = None,
    secondary_override: str | None = None,
) -> tuple[str, int]:
    """Return (freq_str, hop_interval) for the secondary radio in auto multi-mode.

    plan:
      - 'auto' : infer using country_code; if unknown, hop 868+915
      - 'eu'   : 868M
      - 'us'   : 915M
      - 'world': hop 868M,915M
      - 'custom': use secondary_override (if provided), otherwise behave like 'auto'
      - otherwise: treated as custom freq string (e.g. '920M' or '868M,915M')
    """
    p = (plan or "auto").strip().lower()

    if p in ("custom",):
        ov = (secondary_override or "").strip()
        if ov:
            hop = 15 if "," in ov else 0
            return (ov, hop)
        # No override provided; fall back to auto behavior.
        p = "auto"

    if p in ("auto", "detect", "country"):
        cc = (country_code or "").strip().upper()
        if cc in _EU_868_COUNTRIES:
            return ("868M", 0)
        if cc:
            # Default non-EU to 915M. Users can override with plan/custom freq.
            return ("915M", 0)
        # Unknown country: be internationally tolerant by hopping both.
        return ("868M,915M", 15)

    if p in ("eu", "europe", "uk"):
        return ("868M", 0)

    if p in ("us", "usa", "na", "north_america", "north-america", "canada", "au", "australia", "nz", "new_zealand"):
        return ("915M", 0)

    if p in ("world", "global", "intl", "international"):
        return ("868M,915M", 15)

    # Treat anything else as a custom freq string.
    # If multiple freqs are provided, hop interval is enabled.
    freq_str = plan.strip()
    hop = 15 if "," in freq_str else 0
    return (freq_str, hop)


def choose_hopper_band_defaults(
    country_code: str | None = None,
    used_freqs: set[str] | None = None,
) -> str:
    """Return a comma-separated frequency string for the optional 3rd "hopper" radio.

    Goal:
      - Do NOT overlap with the primary/secondary radios (pass used_freqs to enforce this).
      - Be "interesting" (scan bands where people commonly have *other* stuff).

    Notes:
      - This is intentionally opportunistic and may miss bursts while tuned elsewhere.
      - The hopper is best-effort: if all candidates overlap with used_freqs, returns "".

    Candidate bands (ordered by "interesting" likelihood):
      - US/CA/AU/NZ/etc (typically already covering 433 + 915): 315, 345, 390, 868
      - EU/UK/EEA/CH   (typically already covering 433 + 868): 169.4, 915, 315, 345
        * 169.4 MHz is used for some metering in parts of Europe; needs an appropriate antenna.
    """

    cc = (country_code or "").strip().upper()
    u = {s.strip().lower() for s in (used_freqs or set()) if s.strip()}

    if cc and cc in _EU_868_COUNTRIES:
        candidates = ["169.4M", "868.95M", "869.525M", "915M"]
    else:
        candidates = ["315M", "345M", "390M", "868M"]

    chosen = [f for f in candidates if f.strip().lower() not in u]
    return ",".join(chosen)
