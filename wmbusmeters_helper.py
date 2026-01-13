"""wmbusmeters_helper.py

Lightweight integration layer between rtl_433 and wmbusmeters.

Use-case:
- rtl_433 can often demodulate/detect Wireless M-Bus meters but may not decrypt
  OMS/EN13757-4 encrypted payloads.
- wmbusmeters supports AES key based decryption and produces structured JSON.

RTL-HAOS mode:
- Spawn wmbusmeters in decode-only mode (device=stdin:hex) using a generated
  config directory.
- Feed rtl_433's Wireless-MBus `data` hex into wmbusmeters stdin.
- Read JSON lines from wmbusmeters stdout and dispatch them as normal readings.

Design goals:
- Do NOT log keys.
- Fail safely: if wmbusmeters is missing or crashes, RTL-HAOS continues to run
  and falls back to rtl_433 output.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional


_HEX_RE = re.compile(r"^[0-9a-fA-F_]+$")


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    return cleaned or "meter"


def _mask_key(key: str | None) -> str:
    if not key:
        return ""
    key = key.strip()
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}…{key[-4:]}"


@dataclass(frozen=True)
class MeterDef:
    name: str
    id: str
    key: str | None = None
    driver: str | None = None


def build_wmbusmeters_config_dir(config_dir: str, meters: Iterable[MeterDef]) -> Path:
    """Create / refresh a wmbusmeters config directory.

    The directory layout follows wmbusmeters convention:
      <dir>/wmbusmeters.conf
      <dir>/wmbusmeters.d/<meterfile>

    We intentionally keep this in add-on persistent storage (/data) so it survives restarts.
    """

    base = Path(config_dir)
    base.mkdir(parents=True, exist_ok=True)

    meters_dir = base / "wmbusmeters.d"
    meters_dir.mkdir(parents=True, exist_ok=True)

    # Write main config.
    # - device=stdin:hex means we will feed telegram hex strings via stdin.
    # - format=json makes wmbusmeters emit JSON.
    conf = base / "wmbusmeters.conf"
    conf.write_text(
        "\n".join(
            [
                "loglevel=normal",
                "logtelegrams=false",
                "ignoreduplicates=true",
                "format=json",
                "device=stdin:hex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # Refresh meter files.
    # We rewrite deterministically on startup; this prevents stale keys lingering.
    for f in meters_dir.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass

    for m in meters:
        fname = _safe_filename(m.name)
        content_lines = [
            f"name={m.name}",
            f"id={m.id}",
        ]
        if m.key:
            content_lines.append(f"key={m.key}")
        if m.driver:
            content_lines.append(f"driver={m.driver}")

        (meters_dir / fname).write_text("\n".join(content_lines) + "\n", encoding="utf-8")

    return base


class WmbusmetersHelper:
    """Manage a long-running wmbusmeters process and stream JSON results."""

    def __init__(
        self,
        meters: Iterable[MeterDef],
        config_dir: str,
        on_json: Callable[[dict], None],
    ) -> None:
        self._meters = list(meters)
        self._config_dir = config_dir
        self._on_json = on_json

        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if not self._meters:
            return

        build_wmbusmeters_config_dir(self._config_dir, self._meters)

        cmd = [
            "wmbusmeters",
            f"--useconfig={self._config_dir}",
        ]

        # Keep stdout for JSON. Logs typically go to stderr.
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env={**os.environ, "LANG": "C", "LC_ALL": "C"},
        )

        self._reader_thread = threading.Thread(target=self._stdout_reader, daemon=True)
        self._reader_thread.start()

        # Print a concise summary WITHOUT keys.
        meter_summaries = ", ".join(
            [f"{m.name}(id={m.id},key={_mask_key(m.key)})" for m in self._meters]
        )
        print(f"[WMBUS] wmbusmeters helper enabled for: {meter_summaries}")

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None

        if not proc:
            return

        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass

        try:
            proc.terminate()
        except Exception:
            pass

    def feed_hex(self, hex_str: str) -> None:
        """Feed a telegram hex string to wmbusmeters stdin."""
        if not hex_str:
            return

        # wmbusmeters stdin:hex accepts underscores as separators; rtl_433 sometimes emits plain hex.
        payload = hex_str.strip()
        if not _HEX_RE.match(payload):
            # Best-effort: strip spaces and any 0x prefixes if present.
            payload = re.sub(r"[^0-9a-fA-F_]", "", payload)
            if not payload or not _HEX_RE.match(payload):
                return

        with self._lock:
            proc = self._proc
            if not proc or proc.poll() is not None:
                return
            stdin = proc.stdin

        if not stdin:
            return

        try:
            stdin.write(payload + "\n")
            stdin.flush()
        except Exception:
            # If the pipe is broken, the reader thread will observe process exit.
            return

    def _stdout_reader(self) -> None:
        assert self._proc is not None
        proc = self._proc
        if not proc.stdout:
            return

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    self._on_json(obj)
            except Exception:
                # Non-JSON output; ignore.
                continue

        # Process exited.
        code = proc.poll()
        if code is None:
            return
        print(f"[WMBUS] wmbusmeters helper exited (code={code}).")

        # Drain a little stderr for context (no secrets expected here).
        try:
            if proc.stderr:
                tail = proc.stderr.read()[-2000:]
                if tail:
                    print(f"[WMBUS] stderr tail:\n{tail}")
        except Exception:
            pass
