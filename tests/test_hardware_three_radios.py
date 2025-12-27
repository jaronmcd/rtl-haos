"""Hardware-only smoke tests for multi-dongle setups.

These are intentionally skipped unless RUN_HARDWARE_TESTS=1.

They are meant to be run on a dev host where 3+ RTL-SDR dongles are plugged in.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from rtl_manager import discover_rtl_devices


def _require_env(name: str) -> None:
    if os.getenv(name) != "1":
        pytest.skip(f"Set {name}=1 to enable this test")


def _require_rtl433() -> str:
    exe = shutil.which("rtl_433")
    if not exe:
        pytest.skip("rtl_433 is not installed or not in PATH")
    return exe


def _skip_for_common_hw_errors(proc: subprocess.CompletedProcess[str]) -> None:
    combined = (proc.stdout + "\n" + proc.stderr).lower()
    if "no supported devices found" in combined:
        pytest.skip("No RTL-SDR device detected (rtl_433 reported none found)")
    if "usb_open error" in combined or "permission denied" in combined:
        pytest.skip("RTL-SDR present but not accessible (permissions/USB open error)")
    if "resource busy" in combined or "device or resource busy" in combined:
        pytest.skip("RTL-SDR device busy (another rtl_433/add-on instance likely running)")


@pytest.mark.hardware
def test_three_dongles_discoverable_and_openable() -> None:
    """If 3 dongles are present, make sure we can open each one.

    - Discovery uses rtl_eeprom scanning (same logic the add-on uses).
    - For each of the first 3 devices, run rtl_433 briefly with -d <index>.

    We skip (not fail) if fewer than 3 dongles are plugged in.
    """
    _require_env("RUN_HARDWARE_TESTS")
    exe = _require_rtl433()

    devices = discover_rtl_devices()
    if len(devices) < 3:
        pytest.skip(f"Need 3 RTL-SDR devices for this test; found {len(devices)}")

    indices = [d.get("index") for d in devices[:3]]
    assert all(isinstance(i, int) for i in indices)
    assert len(set(indices)) == 3

    serials = [str(d.get("id") or "").strip() for d in devices[:3]]
    assert all(serials), "All three dongles should have a non-empty serial id"

    for idx in indices:
        proc = subprocess.run(
            [exe, "-d", str(idx), "-T", "2", "-F", "json"],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if proc.returncode != 0:
            _skip_for_common_hw_errors(proc)

        assert proc.returncode == 0, (
            f"rtl_433 failed for device index {idx}\n"
            f"STDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
        )

