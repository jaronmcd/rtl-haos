def test_main_highlight_json_and_source_color(monkeypatch):
    import main

    # get_source_color branches
    assert main.get_source_color("MQTT") == main.c_magenta
    assert main.get_source_color("rtl") == main.c_magenta
    assert main.get_source_color("STARTUP") == main.c_magenta
    assert main.get_source_color("nuke") == main.c_red
    assert main.get_source_color("other") == main.c_cyan

    # highlight_json should colorize keys and values (basic smoke assertion)
    colored = main.highlight_json('{"temp_c": 21.5, "state": "ok", "flag": true}')
    assert main.c_cyan in colored  # keys
    assert main.c_white in colored  # values/colons


def test_main_timestamped_print_formats_startup_and_debug(monkeypatch):
    import main

    captured = []

    # Make timestamp deterministic
    class FakeNow:
        def strftime(self, _fmt):
            return "12:34:56"

    class FakeDateTime:
        @staticmethod
        def now():
            return FakeNow()

    monkeypatch.setattr(main, "datetime", FakeDateTime)

    # Capture what timestamped_print emits
    def fake_original_print(msg, *a, **k):
        captured.append(msg)

    monkeypatch.setattr(main, "_original_print", fake_original_print)

    main.timestamped_print("[STARTUP] Hello world")
    main.timestamped_print('[DEBUG] {"a": 1}')

    assert captured, "Expected timestamped_print to call _original_print"
    joined = "\n".join(captured)
    assert "[12:34:56]" in joined
    assert "INFO" in joined
    assert "DEBUG" in joined
    assert main.c_magenta in joined or main.c_cyan in joined  # some ANSI


def test_main_get_version_reads_config_yaml(tmp_path, monkeypatch):
    import main

    # Ensure build metadata does not affect this base-version test.
    monkeypatch.delenv("RTL_HAOS_BUILD", raising=False)
    monkeypatch.delenv("RTL_HAOS_TWEAK", raising=False)

    (tmp_path / "config.yaml").write_text('name: x\nversion: "1.2.3"\n')
    monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))

    assert main.get_version() == "v1.2.3"


def test_main_show_logo_writes_to_stdout(capsys):
    import main

    main.show_logo("v9.9.9")
    out = capsys.readouterr().out
    assert "RTL-SDR Bridge for Home Assistant" in out
    assert "v9.9.9" in out
