import os
import pytest

pytestmark = pytest.mark.integration


def _find_flag_value(cmd, flag):
    try:
        i = cmd.index(flag)
    except ValueError:
        return None
    if i + 1 >= len(cmd):
        return None
    return cmd[i + 1]


def _skip_if_disabled():
    if os.getenv("RUN_RTL433_TESTS", "0") != "1":
        pytest.skip("RUN_RTL433_TESTS not enabled")


def test_rtl_loop_builds_cmd_includes_device_freq_rate(monkeypatch):
    """
    rtl_loop is designed to run forever. This test stops it immediately by raising
    KeyboardInterrupt from the patched subprocess.Popen (KeyboardInterrupt is a BaseException
    and typically won't be swallowed by broad 'except Exception' handlers).
    """
    _skip_if_disabled()

    import rtl_manager  # your module
    captured = {"cmd": None}

    def fake_popen(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        raise KeyboardInterrupt()

    monkeypatch.setattr(rtl_manager.subprocess, "Popen", fake_popen)

    radio = {
        "index": 0,
        "freq": "433.92M",
        "rate": "250k",
        "hop_interval": 0,
        "name": "TestRadio1",
        "id": "101",
        "slot": 0,
    }

    with pytest.raises(KeyboardInterrupt):
        rtl_manager.rtl_loop(radio, object(), object(), "sysid", "sysmodel")

    cmd = captured["cmd"]
    assert cmd is not None, "rtl_loop did not reach subprocess.Popen"
    cmd_str = " ".join(map(str, cmd))

    assert "rtl_433" in cmd_str, f"Expected rtl_433 in command, got: {cmd}"
    assert ("-d" in cmd and str(radio["index"]) in cmd) or ("-d0" in cmd_str), f"Expected device index in cmd: {cmd}"
    assert "433.92M" in cmd_str, f"Expected frequency in cmd: {cmd}"
    assert ("-s" in cmd and "250k" in cmd) or ("250k" in cmd_str), f"Expected rate in cmd: {cmd}"


def test_rtl_loop_multi_freq_adds_hop_interval_when_needed(monkeypatch):
    _skip_if_disabled()

    import rtl_manager
    captured = {"cmd": None}

    def fake_popen(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        raise KeyboardInterrupt()

    monkeypatch.setattr(rtl_manager.subprocess, "Popen", fake_popen)

    radio = {
        "index": 1,
        "freq": "868M,915M",
        "rate": "1024k",
        "hop_interval": 15,
        "name": "TestRadio2",
        "id": "102",
        "slot": 1,
    }

    with pytest.raises(KeyboardInterrupt):
        rtl_manager.rtl_loop(radio, object(), object(), "sysid", "sysmodel")

    cmd = captured["cmd"]
    assert cmd is not None, "rtl_loop did not reach subprocess.Popen"
    cmd_str = " ".join(map(str, cmd))

    assert "868M" in cmd_str and "915M" in cmd_str, f"Expected both freqs in cmd: {cmd}"

    hop_val = _find_flag_value(cmd, "-H")
    if hop_val is None:
        assert ("-H15" in cmd_str) or ("hop" in cmd_str.lower() and "15" in cmd_str), f"Expected hop interval evidence in cmd: {cmd}"
    else:
        assert str(hop_val).strip() == "15", f"Expected hop interval 15, got {hop_val} in cmd: {cmd}"


def test_rtl_loop_single_freq_does_not_require_hop(monkeypatch):
    _skip_if_disabled()

    import rtl_manager
    captured = {"cmd": None}

    def fake_popen(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        raise KeyboardInterrupt()

    monkeypatch.setattr(rtl_manager.subprocess, "Popen", fake_popen)

    radio = {
        "index": 2,
        "freq": "915M",
        "rate": "1024k",
        "hop_interval": 15,
        "name": "TestRadio3",
        "id": "103",
        "slot": 2,
    }

    with pytest.raises(KeyboardInterrupt):
        rtl_manager.rtl_loop(radio, object(), object(), "sysid", "sysmodel")

    cmd = captured["cmd"]
    assert cmd is not None
    cmd_str = " ".join(map(str, cmd))
    assert "915M" in cmd_str
