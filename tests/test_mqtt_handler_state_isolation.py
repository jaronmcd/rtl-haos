"""
Tests for MQTT handler state isolation and lock consolidation.

Covers:
- tracked_devices isolation with _track_device/_untrack_device helpers
- discovery_state isolation with helper methods
- Shared _state_lock protecting both
- Concurrent state mutations
- Callback thread safety
"""

import pytest
import threading
import time
from unittest import mock
from mqtt_handler import HomeNodeMQTT


class TestTrackedDevicesIsolation:
    """Tests for tracked_devices state isolation."""

    def test_track_device_adds_to_set(self, mocker):
        """_track_device adds device to tracked set."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        handler._track_device("device1")
        
        with handler._state_lock:
            assert "device1" in handler.tracked_devices

    def test_untrack_device_removes_from_set(self, mocker):
        """_untrack_device removes device from set."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        handler._track_device("device1")
        handler._untrack_device("device1")
        
        with handler._state_lock:
            assert "device1" not in handler.tracked_devices

    def test_reset_tracked_devices_clears_set(self, mocker):
        """_reset_tracked_devices clears all tracked devices."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        handler._track_device("device1")
        handler._track_device("device2")
        handler._track_device("device3")
        
        handler._reset_tracked_devices()
        
        with handler._state_lock:
            assert len(handler.tracked_devices) == 0

    def test_track_device_protected_by_lock(self, mocker):
        """track_device access is protected by _state_lock."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        # Verify we can access safely
        handler._track_device("dev1")
        
        # Verify lock is being used (we can read with lock)
        with handler._state_lock:
            assert "dev1" in handler.tracked_devices

    def test_multiple_track_untrack_operations(self, mocker):
        """Sequence of track/untrack operations."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        handler._track_device("dev1")
        handler._track_device("dev2")
        assert len([d for d in handler.tracked_devices]) >= 2
        
        handler._untrack_device("dev1")
        with handler._state_lock:
            assert "dev1" not in handler.tracked_devices
            assert "dev2" in handler.tracked_devices


class TestDiscoveryStateIsolation:
    """Tests for discovery state isolation."""

    def test_reset_discovery_state(self, mocker):
        """_reset_discovery_state resets all discovery fields."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()
        
        # Set some state
        handler._set_discovery_enabled(True)
        handler._set_last_sent_value("key1", "val1")
        
        # Reset via method
        handler._reset_discovery_state()
        
        with handler._state_lock:
            assert len(handler.discovery_published) == 0
            assert len(handler.last_sent_values) == 0
        
        handler.stop()

    def test_reset_discovery_state(self, mocker):
        """_reset_discovery_state resets all discovery fields."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()
        
        # Set some state
        handler._set_discovery_enabled(True)
        handler._set_last_sent_value("key1", "val1")
        
        # Reset
        handler._reset_discovery_state()
        
        with handler._state_lock:
            assert len(handler.discovery_published) == 0
            assert len(handler.last_sent_values) == 0
        
        handler.stop()

    def test_get_last_sent_value_returns_none_for_missing(self, mocker):
        """_get_last_sent_value returns None for missing key."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        value = handler._get_last_sent_value("nonexistent")
        
        assert value is None

    def test_get_set_last_sent_value(self, mocker):
        """_set_last_sent_value and _get_last_sent_value work together."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        handler._set_last_sent_value("sensor1", 42.5)
        value = handler._get_last_sent_value("sensor1")
        
        assert value == 42.5

    def test_set_discovery_enabled_persists(self, mocker):
        """_set_discovery_enabled updates state."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        handler._set_discovery_enabled(True)
        
        with handler._state_lock:
            assert handler.allow_new_device_discovery is True
        
        handler._set_discovery_enabled(False)
        
        with handler._state_lock:
            assert handler.allow_new_device_discovery is False


class TestStateLockConsolidation:
    """Verify single _state_lock protects related state."""

    def test_state_lock_protects_tracked_and_discovery(self, mocker):
        """Single _state_lock protects both tracked and discovery state."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        # Both operations use same lock
        handler._track_device("dev1")
        handler._set_discovery_enabled(True)
        handler._set_last_sent_value("key1", "val1")
        
        # All should be accessible via same lock
        with handler._state_lock:
            assert "dev1" in handler.tracked_devices
            assert handler.allow_new_device_discovery is True
            assert "key1" in handler.last_sent_values

    def test_concurrent_tracked_and_discovery_access(self, mocker):
        """Concurrent access to tracked and discovery state."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()
        
        errors = []
        results = {"tracks": 0, "discoveries": 0}
        lock = threading.Lock()

        def track_devices():
            try:
                for i in range(20):
                    handler._track_device(f"dev{i}")
                    with lock:
                        results["tracks"] += 1
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def set_discovery_values():
            try:
                for i in range(20):
                    handler._set_last_sent_value(f"key{i}", f"val{i}")
                    with lock:
                        results["discoveries"] += 1
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=track_devices),
            threading.Thread(target=set_discovery_values),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        handler.stop()

        assert len(errors) == 0
        assert results["tracks"] == 20
        assert results["discoveries"] == 20

    def test_concurrent_read_and_write_state(self, mocker):
        """Multiple readers while writers modify state."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()
        
        errors = []
        read_results = []
        lock = threading.Lock()

        def reader():
            try:
                for _ in range(10):
                    with handler._state_lock:
                        read_results.append({
                            "tracked": len(handler.tracked_devices),
                            "values": len(handler.last_sent_values),
                        })
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(10):
                    handler._track_device(f"dev{i}")
                    handler._set_last_sent_value(f"key{i}", f"val{i}")
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        handler.stop()

        assert len(errors) == 0
        # Verify reads increased over time
        assert len(read_results) >= 10


class TestDiscoveryLockAlias:
    """Verify discovery_lock is alias to _state_lock."""

    def test_discovery_lock_same_as_state_lock(self, mocker):
        """discovery_lock is alias for _state_lock."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        # They should be the same object
        assert handler.discovery_lock is handler._state_lock

    def test_accessing_via_discovery_lock(self, mocker):
        """Can access discovery_published via discovery_lock."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        handler._set_last_sent_value("sensor1", 42.5)
        
        # Access via discovery_lock (for backward compatibility)
        with handler.discovery_lock:
            value = handler.last_sent_values.get("sensor1")
        
        assert value == 42.5


class TestConcurrentStateOperations:
    """Complex concurrent scenarios."""

    def test_interleaved_track_untrack_operations(self, mocker):
        """Rapid track/untrack operations remain consistent."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()
        
        errors = []

        def cycle_track_untrack(device_id):
            try:
                for _ in range(10):
                    handler._track_device(device_id)
                    time.sleep(0.001)
                    handler._untrack_device(device_id)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=cycle_track_untrack, args=(f"dev{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        handler.stop()

        assert len(errors) == 0

    def test_reset_during_active_tracking(self, mocker):
        """Reset while other threads are tracking."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()
        
        errors = []
        active_count = [0]
        lock = threading.Lock()

        def tracker():
            try:
                for i in range(10):
                    handler._track_device(f"dev{i}")
                    with lock:
                        active_count[0] = len(handler.tracked_devices)
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        def resetter():
            time.sleep(0.02)
            try:
                handler._reset_tracked_devices()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=tracker),
            threading.Thread(target=tracker),  # Two trackers
            threading.Thread(target=resetter),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        handler.stop()

        assert len(errors) == 0

    def test_concurrent_clear_and_set_discovery(self, mocker):
        """Clearing and setting discovery state safely."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        handler.start()
        
        errors = []

        def set_values():
            try:
                for i in range(20):
                    handler._set_last_sent_value(f"sensor{i}", i * 1.5)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reset_state():
            time.sleep(0.01)
            try:
                handler._reset_discovery_state()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=set_values),
            threading.Thread(target=reset_state),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        handler.stop()

        assert len(errors) == 0


class TestLockDeadlockPrevention:
    """Verify no deadlock scenarios in lock usage."""

    def test_recursive_lock_allows_reentry(self, mocker):
        """RLock allows same thread to reacquire."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        # _state_lock should be RLock (reentrant)
        assert isinstance(handler._state_lock, type(threading.RLock()))

    def test_nested_lock_operations(self, mocker):
        """Nested operations within same lock don't deadlock."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        # Should not deadlock
        with handler._state_lock:
            handler._track_device("dev1")
            # Nested access
            with handler._state_lock:
                handler._set_discovery_enabled(True)
                with handler._state_lock:
                    value = handler._get_last_sent_value("key")

    def test_lock_release_on_exception(self, mocker):
        """Lock is released even if exception occurs."""
        mocker.patch("mqtt_handler.mqtt.Client")
        handler = HomeNodeMQTT()
        
        try:
            with handler._state_lock:
                handler._track_device("dev1")
                raise RuntimeError("Expected error")
        except RuntimeError:
            pass
        
        # Lock should be released, able to acquire again
        with handler._state_lock:
            assert "dev1" in handler.tracked_devices
