# tests/conftest.py
import os
import sys
import types
import importlib.machinery
import unittest.mock as um
import warnings
import pytest
import config
# Some container/CI environments ship a vendored psutil (e.g. via ddtrace) that
# emits noisy RuntimeWarnings on import due to missing /proc/vmstat.
warnings.filterwarnings(
    "ignore",
    message=r".*swap memory stats couldn't be determined.*",
    category=RuntimeWarning,
)

@pytest.fixture(autouse=True)
def _isolate_device_filters(monkeypatch):
    # Tests should not be affected by a developer's .env / HA options.
    monkeypatch.setattr(config, "DEVICE_WHITELIST", [], raising=False)

    # Preserve expected behavior: SimpliSafe remains blocked in tests that assert it.
    monkeypatch.setattr(config, "DEVICE_BLACKLIST", ["SimpliSafe*", "EezTire*"], raising=False)


@pytest.fixture(autouse=True)
def _clear_build_metadata_env(monkeypatch):
    """Keep tests deterministic regardless of the developer's shell env.

    RTL-HAOS can append optional build metadata (RTL_HAOS_BUILD/RTL_HAOS_TWEAK)
    to the displayed version. Tests should explicitly set these env vars when
    needed, rather than inheriting them from the host environment.
    """
    monkeypatch.delenv("RTL_HAOS_BUILD", raising=False)
    monkeypatch.delenv("RTL_HAOS_TWEAK", raising=False)

# Ensure we can import project modules from repo root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# If psutil isn't installed in some environments, provide a tiny stub module.
# (Also ensures __spec__ exists so importlib.util.find_spec("psutil") won't ValueError.)
try:
    import psutil  # noqa: F401
except ImportError:
    stub = types.ModuleType("psutil")
    stub.__spec__ = importlib.machinery.ModuleSpec("psutil", loader=None)
    sys.modules["psutil"] = stub


# ---------------------------------------------------------------------------
# Minimal "mocker" fixture (fallback)
# ---------------------------------------------------------------------------
#
# This repo uses the pytest-mock fixture name (`mocker`) extensively.
# If pytest-mock is installed, it will provide the real fixture.
# If it isn't, we provide a tiny compatible shim that supports what the tests
# in this repository actually use:
#   - mocker.patch(...)
#   - mocker.patch.object(...)
#   - mocker.Mock(), mocker.MagicMock()
#
try:
    import pytest_mock  # noqa: F401
    _HAS_PYTEST_MOCK = True
except Exception:
    _HAS_PYTEST_MOCK = False


if not _HAS_PYTEST_MOCK:

    class _Patcher:
        def __init__(self, parent: "_SimpleMocker"):
            self._parent = parent

        def __call__(self, target, *args, **kwargs):
            p = um.patch(target, *args, **kwargs)
            m = p.start()
            self._parent._patches.append(p)
            return m

        def object(self, target, attribute, *args, **kwargs):
            p = um.patch.object(target, attribute, *args, **kwargs)
            m = p.start()
            self._parent._patches.append(p)
            return m

    class _SimpleMocker:
        def __init__(self):
            self._patches = []
            self.patch = _Patcher(self)

            # Convenience aliases used by tests
            self.Mock = um.Mock
            self.MagicMock = um.MagicMock

        def stopall(self):
            for p in reversed(self._patches):
                try:
                    p.stop()
                except RuntimeError:
                    # Patch already stopped
                    pass
            self._patches.clear()

    @pytest.fixture
    def mocker():
        m = _SimpleMocker()
        try:
            yield m
        finally:
            m.stopall()


@pytest.fixture
def mock_config(mocker):
    """Patches configuration so tests can control settings without env files."""

    mocker.patch("config.BRIDGE_ID", "TEST_BRIDGE")
    mocker.patch("config.BRIDGE_NAME", "Test Home")

    # Make throttling instant for tests
    mocker.patch("config.RTL_THROTTLE_INTERVAL", 0)

    # Default filtering behavior for tests
    mocker.patch("config.DEVICE_BLACKLIST", ["SimpliSafe*", "BadDevice*"])
    mocker.patch("config.DEVICE_WHITELIST", [])

    # Fixture is side-effect only
    return None
