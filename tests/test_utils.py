import pytest
from utils import clean_mac, calculate_dew_point, validate_radio_config
from utils import get_system_mac

def test_system_id_stability(mocker):
    """
    Ensures the system ID prefers the Config ID, then falls back to Hostname.
    """
    # Case 1: Config ID is set (Preferred)
    mocker.patch("config.BRIDGE_ID", "static-id-123")
    # Reset the cache global variable for the test
    mocker.patch("utils._SYSTEM_MAC", None)
    
    assert get_system_mac() == "static-id-123"

    # Case 2: Config ID is Missing -> Use Hostname
    mocker.patch("config.BRIDGE_ID", None)
    mocker.patch("utils._SYSTEM_MAC", None) # Reset cache
    mocker.patch("socket.gethostname", return_value="my-host-name")
    
    assert get_system_mac() == "my-host-name"

    # Case 3: Hostname fails -> Fallback
    mocker.patch("config.BRIDGE_ID", None)
    mocker.patch("utils._SYSTEM_MAC", None) # Reset cache
    mocker.patch("socket.gethostname", return_value="")
    
    assert get_system_mac() == "rtl-bridge-default"
    
def test_clean_mac():
    assert clean_mac("12:34:AB") == "1234ab"
    assert clean_mac("  My Device  ") == "mydevice"
    # Code converts None -> "None" -> "none"
    assert clean_mac(None) == "none"

def test_calculate_dew_point():
    # Standard check: 20C at 50% humidity is approx 9.3C (48.7F)
    dp = calculate_dew_point(20, 50)
    assert 48.0 <= dp <= 50.0

    # Edge cases
    assert calculate_dew_point(None, 50) is None
    assert calculate_dew_point(20, None) is None
    assert calculate_dew_point(20, 0) is None # Invalid humidity

def test_validate_radio_config():
    # 1. Valid Config
    valid = {"id": "100", "freq": "433.92M", "rate": "250k"}
    assert len(validate_radio_config(valid)) == 0

    # 2. Missing ID (Should Warn)
    no_id = {"freq": "433.92M"}
    warns = validate_radio_config(no_id)
    assert len(warns) == 1
    assert "missing a device 'id'" in warns[0]

    # 3. Bad Frequency (No 'M')
    bad_freq = {"id": "1", "freq": "433"} 
    warns = validate_radio_config(bad_freq)
    assert any("impossible" in w for w in warns)

    # 4. Bad Rate (No 'k')
    bad_rate = {"id": "1", "rate": "250"}
    warns = validate_radio_config(bad_rate)
    assert any("did you mean '250k'" in w.lower() for w in warns)

def test_validate_radio_config_does_not_require_id_for_rtl_tcp_device():
    # device selector implies explicit device choice; id warning should NOT trigger
    cfg = {"name": "PC rtl_tcp", "freq": "433.92M", "device": "rtl_tcp:192.168.1.223:1234"}
    warns = validate_radio_config(cfg)
    assert not any("missing a device 'id'" in w.lower() for w in warns)


def test_validate_radio_config_does_not_require_id_for_tcp_host_port():
    cfg = {"name": "PC rtl_tcp", "freq": "433.92M", "tcp_host": "192.168.1.223", "tcp_port": 1234}
    warns = validate_radio_config(cfg)
    assert not any("missing a device 'id'" in w.lower() for w in warns)


def test_validate_radio_config_warns_on_bad_rtl_tcp_device_port():
    cfg = {"name": "Bad rtl_tcp", "freq": "433.92M", "device": "rtl_tcp:192.168.1.223:notaport"}
    warns = validate_radio_config(cfg)
    assert any("not numeric" in w.lower() for w in warns)


def test_validate_radio_config_warns_on_invalid_hop_interval_string():
    cfg = {"id": "1", "freq": "868M,915M", "hop_interval": "abc"}
    warns = validate_radio_config(cfg)
    assert any("not a valid integer" in w.lower() for w in warns)
