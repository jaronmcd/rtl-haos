import pytest
from rtl_manager import is_blocked_device, is_allowed_device

def test_blacklist_logic(mocker):
    """
    Verifies that devices are correctly blocked by ID, Model, or Type.
    """
    # 1. Setup Config with Wildcards
    # We block:
    # - Any ID starting with '123'
    # - Any Model containing 'Tire'
    # - Any Type equal to 'smoke'
    mock_blacklist = ["123*", "*Tire*", "smoke"]
    mocker.patch("config.DEVICE_BLACKLIST", mock_blacklist)

    # 2. Test Cases that should be BLOCKED (True)
    assert is_blocked_device("12345", "Generic", "weather") is True  # Matches ID wildcard
    assert is_blocked_device("99999", "EezTire", "pressure") is True # Matches Model wildcard
    assert is_blocked_device("55555", "Nest", "smoke") is True       # Matches Type exact

    # 3. Test Cases that should be ALLOWED (False)
    assert is_blocked_device("98765", "Generic", "weather") is False
    assert is_blocked_device("55555", "Nest", "co2") is False


def test_whitelist_logic_matches_id_model_type_and_raw_id(mocker):
    """Whitelist should allow by ID, Model, or Type (glob patterns).

    Regression for cases where whitelist was applied only to the cleaned ID.
    """

    # Match by exact model
    mocker.patch("config.DEVICE_WHITELIST", ["Cotech-367959"])
    assert is_allowed_device("101", "Cotech-367959", "weather", raw_id=101) is True
    assert is_allowed_device("101", "OtherModel", "weather", raw_id=101) is False

    # Match by model prefix glob
    mocker.patch("config.DEVICE_WHITELIST", ["Cotech*"])
    assert is_allowed_device("101", "Cotech-367959", "weather", raw_id=101) is True

    # Match by ID
    mocker.patch("config.DEVICE_WHITELIST", ["101"])
    assert is_allowed_device("101", "OtherModel", "weather", raw_id=101) is True

    # Match by Type
    mocker.patch("config.DEVICE_WHITELIST", ["wea*"])
    assert is_allowed_device("101", "OtherModel", "weather", raw_id=101) is True

    # Match by raw_id formatting (e.g., with separators)
    mocker.patch("config.DEVICE_WHITELIST", ["AA:BB*"])
    assert is_allowed_device("aabbccdd", "OtherModel", "weather", raw_id="AA:BB:CC:DD") is True