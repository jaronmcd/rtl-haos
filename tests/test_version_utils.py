# tests/test_version_utils.py
import os

import pytest


import version_utils


def test_read_base_version_parses_quoted_and_comments(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text('name: X\nversion: "1.2.3"  # comment\n', encoding="utf-8")
    assert version_utils.read_base_version(str(cfg)) == "1.2.3"


def test_read_base_version_parses_unquoted_and_spacing(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("\n  version: 1.2.3  \n", encoding="utf-8")
    assert version_utils.read_base_version(str(cfg)) == "1.2.3"


def test_read_base_version_returns_unknown_when_missing(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("name: X\n", encoding="utf-8")
    assert version_utils.read_base_version(str(cfg)) == "Unknown"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("+g3f2 a9c1", "g3f2-a9c1"),
        (" dev build ", "dev-build"),
        ("a..b...c", "a.b.c"),
        ("---a---", "a"),
        ("..--..", None),
        ("", None),
    ],
)
def test_sanitize_build(raw, expected):
    assert version_utils._sanitize_build(raw) == expected


def test_get_build_metadata_prefers_build_over_tweak(monkeypatch):
    monkeypatch.setenv("RTL_HAOS_BUILD", "build123")
    monkeypatch.setenv("RTL_HAOS_TWEAK", "tweak999")
    assert version_utils.get_build_metadata() == "build123"


def test_get_build_metadata_falls_back_to_tweak(monkeypatch):
    monkeypatch.delenv("RTL_HAOS_BUILD", raising=False)
    monkeypatch.setenv("RTL_HAOS_TWEAK", "tweak999")
    assert version_utils.get_build_metadata() == "tweak999"


def test_format_display_version_handles_prefix_and_build():
    assert version_utils.format_display_version("1.2.3", "abc") == "v1.2.3+abc"
    assert version_utils.format_display_version("1.2.3", "abc", prefix="") == "1.2.3+abc"
    assert version_utils.format_display_version("Unknown", "abc") == "Unknown"


def test_get_display_version_combines_file_and_env(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text('name: X\nversion: "1.2.3"\n', encoding="utf-8")
    monkeypatch.setenv("RTL_HAOS_BUILD", "dev build")
    assert version_utils.get_display_version(str(cfg)) == "v1.2.3+dev-build"


def test_get_display_version_no_build(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text('name: X\nversion: "1.2.3"\n', encoding="utf-8")
    monkeypatch.delenv("RTL_HAOS_BUILD", raising=False)
    monkeypatch.delenv("RTL_HAOS_TWEAK", raising=False)
    assert version_utils.get_display_version(str(cfg)) == "v1.2.3"


def test_notify_version_major_minor():
    assert version_utils.notify_version_major_minor("1.2.3") == "1.2.0"
    assert version_utils.notify_version_major_minor("  10.20.30 ") == "10.20.0"
    assert version_utils.notify_version_major_minor("v1.2.3") is None
    assert version_utils.notify_version_major_minor("1.2") is None
