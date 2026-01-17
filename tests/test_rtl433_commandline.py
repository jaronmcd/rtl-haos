"""Unit tests for rtl_433 command construction and loop wiring.

These tests DO NOT execute the external `rtl_433` binary. We patch subprocess.Popen
and focus on verifying the command list that would be executed.

Why this file exists:
- rtl_433 passthrough (global + per-radio) is a core feature and should be covered
  by the default test suite / CI.
- RUN_RTL433_TESTS should only be required for tests that *actually run* rtl_433.
"""

import pytest


def _find_flag_value(cmd, flag):
    try:
        i = cmd.index(flag)
    except ValueError:
        return None
    if i + 1 >= len(cmd):
        return None
    return cmd[i + 1]


def _run_rtl_loop_one_shot(monkeypatch, rtl_manager, radio):
    """Run rtl_loop until it attempts to spawn rtl_433, then stop via KeyboardInterrupt."""
    captured = {"cmd": None}

    def fake_popen(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        raise KeyboardInterrupt()

    monkeypatch.setattr(rtl_manager.subprocess, "Popen", fake_popen)

    with pytest.raises(KeyboardInterrupt):
        rtl_manager.rtl_loop(radio, mqtt_handler=None, data_processor=None, sys_id="sys", sys_model="rtl-haos")

    assert captured["cmd"] is not None
    return captured["cmd"]


def test_rtl_loop_builds_cmd_includes_device_freq_rate(monkeypatch):
    import rtl_manager

    radio = {
        "index": 0,
        "freq": "433.92M",
        "rate": "250k",
        "hop_interval": 0,
        "name": "TestRadio1",
        "id": "101",
    }

    cmd = _run_rtl_loop_one_shot(monkeypatch, rtl_manager, radio)

    assert cmd[0]  # binary name present
    assert "-d" in cmd
    assert _find_flag_value(cmd, "-d") in ("0", 0)
    assert "-f" in cmd
    assert _find_flag_value(cmd, "-f") == "433.92M"
    assert "-s" in cmd
    assert _find_flag_value(cmd, "-s") == "250k"


def test_rtl_loop_logs_command_line_per_radio(monkeypatch, capsys):
    """Startup logs should include the exact rtl_433 command line per radio."""
    import rtl_manager

    def fake_popen(cmd, *args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(rtl_manager.subprocess, "Popen", fake_popen)

    radio = {
        "index": 0,
        "freq": "433.92M",
        "rate": "250k",
        "hop_interval": 0,
        "name": "RadioA",
        "id": "101",
    }

    with pytest.raises(KeyboardInterrupt):
        rtl_manager.rtl_loop(radio, mqtt_handler=None, data_processor=None, sys_id="sys", sys_model="rtl-haos")

    out = capsys.readouterr().out
    assert "rtl_433 cmd [radioa id=101]" in out.lower()
    # Copy/paste friendly flags should be present.
    assert "-d 0" in out
    assert "-f 433.92m" in out.lower()
    assert "-s 250k" in out.lower()
    assert "-f json" in out.lower()
    assert "-m level" in out.lower()


def test_rtl_loop_multi_freq_adds_hop_interval_when_needed(monkeypatch):
    import rtl_manager

    radio = {
        "index": 1,
        "freq": "868M,915M",
        "rate": "1024k",
        "hop_interval": 15,
        "name": "TestRadio2",
        "id": "102",
    }

    cmd = _run_rtl_loop_one_shot(monkeypatch, rtl_manager, radio)

    cmd_str = " ".join(map(str, cmd))
    assert "868M" in cmd_str and "915M" in cmd_str
    assert "-H" in cmd, f"Expected hop flag -H in cmd: {cmd}"
    assert _find_flag_value(cmd, "-H") in ("15", 15)


def test_rtl_loop_single_freq_does_not_require_hop(monkeypatch):
    import rtl_manager

    radio = {
        "index": 2,
        "freq": "915M",
        "rate": "250k",
        "hop_interval": 15,  # should be ignored for single freq
        "name": "TestRadio3",
        "id": "103",
    }

    cmd = _run_rtl_loop_one_shot(monkeypatch, rtl_manager, radio)

    assert "-H" not in cmd, f"Did not expect hop flag for single frequency: {cmd}"
    cmd_str = " ".join(map(str, cmd))
    assert "915M" in cmd_str


def test_build_cmd_includes_global_and_per_radio_passthrough(monkeypatch):
    """Passthrough: global RTL_433_ARGS + per-radio args both appear in command."""
    import config
    import rtl_manager

    monkeypatch.setattr(config, "RTL_433_ARGS", "-g 0 -p 70")
    radio = {
        "index": 0,
        "freq": "915M",
        "rate": "250k",
        "hop_interval": 0,
        "name": "TestRadio",
        "id": "201",
        "args": "-R 11",
    }

    cmd = rtl_manager.build_rtl_433_command(radio)
    cmd_str = " ".join(map(str, cmd))

    # global args present
    assert "-g 0" in cmd_str
    assert "-p 70" in cmd_str
    # per-radio args present
    assert "-R 11" in cmd_str


def test_build_cmd_accepts_json_list_global_args(monkeypatch):
    """Global passthrough may come from HA UI as a JSON list string."""
    import config
    import rtl_manager

    monkeypatch.setattr(config, "RTL_433_ARGS", '["-g","0","-R","11"]')
    radio = {
        "index": 0,
        "freq": "915M",
        "rate": "250k",
        "hop_interval": 0,
        "name": "TestRadio",
        "id": "202",
    }

    cmd = rtl_manager.build_rtl_433_command(radio)
    cmd_str = " ".join(map(str, cmd))
    assert "-g 0" in cmd_str
    assert "-R 11" in cmd_str


def test_build_cmd_config_path_resolves_when_file_exists(monkeypatch, tmp_path):
    """If a relative config_path exists in CWD, it should resolve to an absolute path."""
    import rtl_manager

    cfg = tmp_path / "rtl_433.conf"
    cfg.write_text("# test config\n", encoding="utf-8")

    # The resolver checks Path.cwd() / <relative>, so set cwd to tmp_path
    monkeypatch.chdir(tmp_path)

    radio = {
        "index": 0,
        "freq": "915M",
        "rate": "250k",
        "hop_interval": 0,
        "name": "TestRadio",
        "id": "203",
        "config_path": "rtl_433.conf",
    }

    cmd = rtl_manager.build_rtl_433_command(radio)
    assert "-c" in cmd
    c_idx = cmd.index("-c")
    assert cmd[c_idx + 1] == str(cfg)


def test_build_cmd_inline_config_writes_temp_file(monkeypatch):
    """Inline config: content should be written to a temp file and referenced with -c."""
    import rtl_manager

    radio = {
        "index": 0,
        "freq": "915M",
        "rate": "250k",
        "hop_interval": 0,
        "name": "TestRadio",
        "id": "204",
        "config_inline": "-g 0\n-R 11\n",
        "slot": 3,
    }

    cmd = rtl_manager.build_rtl_433_command(radio)
    assert "-c" in cmd, f"Expected -c <path> in cmd: {cmd}"
    c_idx = cmd.index("-c")
    cfg_path = cmd[c_idx + 1]
    assert cfg_path.startswith("/tmp/rtl_433_"), f"Expected temp config under /tmp, got {cfg_path}"

    # File should exist and contain our content.
    with open(cfg_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "-g 0" in content and "-R 11" in content


def test_rtl433_args_overrides_per_radio_settings_and_warns(monkeypatch, capsys):
    """Global RTL_433_ARGS should override per-radio defaults/args and emit a WARNING."""
    import config
    import rtl_manager

    # Global override forces sample rate and ppm for ALL radios.
    monkeypatch.setattr(config, "RTL_433_ARGS", "-s 2000k -p -1")

    radio = {
        "index": 0,
        "freq": "433.92M",
        "rate": "250k",
        "hop_interval": 0,
        "name": "TestRadio",
        "id": "101",
        # Per-radio args also try to set sample rate; global should win.
        "args": "-s 1024k",
    }

    cmd = rtl_manager.build_rtl_433_command(radio)
    cmd_str = " ".join(map(str, cmd))

    # Only ONE '-s' and it should be the global override.
    assert cmd.count("-s") == 1
    assert _find_flag_value(cmd, "-s") == "2000k"
    assert "1024k" not in cmd_str
    assert "250k" not in cmd_str

    out = (capsys.readouterr().out or "").lower()
    assert "warning" in out
    assert "override" in out
    assert "-s" in out

def test_build_cmd_uses_device_selector_rtl_tcp(monkeypatch):
    import rtl_manager

    radio = {
        "index": 0,
        "freq": "433.92M",
        "rate": "250k",
        "hop_interval": 0,
        "name": "PC rtl_tcp",
        "device": "rtl_tcp:192.168.1.223:1234",
    }

    cmd = rtl_manager.build_rtl_433_command(radio)
    assert _find_flag_value(cmd, "-d") == "rtl_tcp:192.168.1.223:1234"


def test_build_cmd_uses_tcp_host_port_over_device(monkeypatch):
    import rtl_manager

    radio = {
        "index": 0,
        "freq": "433.92M",
        "rate": "250k",
        "hop_interval": 0,
        "name": "PC rtl_tcp",
        "device": "0",  # should be ignored because tcp_host is set
        "tcp_host": "192.168.1.223",
        "tcp_port": 1234,
    }

    cmd = rtl_manager.build_rtl_433_command(radio)
    assert _find_flag_value(cmd, "-d") == "rtl_tcp:192.168.1.223:1234"


def test_build_cmd_tcp_port_defaults_to_1234_when_missing(monkeypatch):
    import rtl_manager

    radio = {
        "index": 0,
        "freq": "433.92M",
        "rate": "250k",
        "hop_interval": 0,
        "name": "PC rtl_tcp",
        "tcp_host": "192.168.1.223",
        # tcp_port omitted
    }

    cmd = rtl_manager.build_rtl_433_command(radio)
    assert _find_flag_value(cmd, "-d") == "rtl_tcp:192.168.1.223:1234"
