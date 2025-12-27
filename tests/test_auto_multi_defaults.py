import pytest

from utils import choose_secondary_band_defaults, choose_hopper_band_defaults


def test_choose_secondary_auto_us_defaults_to_915() -> None:
    freq, hop = choose_secondary_band_defaults(plan="auto", country_code="US")
    assert freq == "915M"
    assert hop == 0


def test_choose_secondary_auto_eu_defaults_to_868() -> None:
    freq, hop = choose_secondary_band_defaults(plan="auto", country_code="DE")
    assert freq == "868M"
    assert hop == 0


def test_choose_secondary_auto_unknown_hops_868_915() -> None:
    freq, hop = choose_secondary_band_defaults(plan="auto", country_code=None)
    assert freq == "868M,915M"
    assert hop == 15


def test_choose_secondary_custom_override_single() -> None:
    freq, hop = choose_secondary_band_defaults(
        plan="custom",
        country_code="US",
        secondary_override="920M",
    )
    assert freq == "920M"
    assert hop == 0


def test_choose_secondary_custom_override_multi_enables_hop() -> None:
    freq, hop = choose_secondary_band_defaults(
        plan="custom",
        country_code="US",
        secondary_override="868M,915M",
    )
    assert freq == "868M,915M"
    assert hop == 15


def test_choose_hopper_us_excludes_used_bands() -> None:
    used = {"433.92m", "915m"}
    freq = choose_hopper_band_defaults(country_code="US", used_freqs=used)
    parts = [p.strip().lower() for p in freq.split(",") if p.strip()]
    assert "915m" not in parts
    # US order is intentional: 315/345 first
    assert parts[:2] == ["315m", "345m"]


def test_choose_hopper_eu_excludes_used_bands() -> None:
    used = {"868m", "868.95m", "915m"}
    freq = choose_hopper_band_defaults(country_code="DE", used_freqs=used)
    parts = [p.strip().lower() for p in freq.split(",") if p.strip()]
    assert "915m" not in parts
    assert "868.95m" not in parts
    assert "169.4m" in parts


