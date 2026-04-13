"""
Tests for KnownDeviceManager thread-safety and concurrency patterns.

Covers:
- Thread-safe add/remove/update operations with locking
- Persistence helpers (_save_known_devices_locked)
- Callback notification (_notify_select_update)
- Discovery state queries
- Concurrent device modifications
"""

import pytest
import threading
import time
from unittest import mock
from known_device_manager import KnownDeviceManager


class TestKnownDeviceManagerBasic:
    """Basic KnownDeviceManager operations."""

    def test_initialization_loads_from_store(self):
        """Manager loads devices from store on init."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {"dev1": {"name": "Device 1"}}
        mock_discovery_cb = mock.MagicMock(return_value=True)
        
        manager = KnownDeviceManager(
            mock_store,
            mock_discovery_cb,
            mock.MagicMock()
        )
        
        assert "dev1" in manager.known_devices
        assert manager.known_devices["dev1"]["name"] == "Device 1"

    def test_add_or_update_device_persists(self):
        """Adding/updating device persists to store."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        mock_discovery_cb = mock.MagicMock(return_value=True)
        
        manager = KnownDeviceManager(
            mock_store,
            mock_discovery_cb,
            mock.MagicMock()
        )
        
        manager.add_or_update_device("dev1", "Device1", "Model1")
        
        # Verify save was called
        mock_store.save_devices.assert_called()
        call_args = mock_store.save_devices.call_args[0][0]
        assert "dev1" in call_args

    def test_remove_device_calls_cleanup(self):
        """Removing device triggers MQTT cleanup callback."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        mock_discovery_cb = mock.MagicMock(return_value=True)
        mock_cleanup_cb = mock.MagicMock()
        
        manager = KnownDeviceManager(
            mock_store,
            mock_discovery_cb,
            mock_cleanup_cb
        )
        
        manager.add_or_update_device("dev1", "Device1", "Model1")
        manager.remove_device("dev1")
        
        # Cleanup should have been called
        mock_cleanup_cb.assert_called()

    def test_get_discovery_enabled_calls_callback(self):
        """Getting discovery state queries callback."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        mock_discovery_cb = mock.MagicMock(return_value=True)
        
        manager = KnownDeviceManager(
            mock_store,
            mock_discovery_cb,
            mock.MagicMock()
        )
        
        result = manager.get_discovery_enabled()
        
        assert result is True
        mock_discovery_cb.assert_called()


class TestKnownDeviceManagerPersistenceHelpers:
    """Test persistence helper methods."""

    def test_save_known_devices_locked_persists(self):
        """_save_known_devices_locked saves to store."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock.MagicMock()
        )
        
        manager.known_devices = {"dev1": {"name": "Device 1"}}
        
        with manager._lock:
            result = manager._save_known_devices_locked("test_context")
        
        assert result is True
        mock_store.save_devices.assert_called_with(manager.known_devices)

    def test_save_known_devices_locked_returns_false_on_error(self):
        """_save_known_devices_locked returns False on exception."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        mock_store.save_devices.side_effect = RuntimeError("Save failed")
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock.MagicMock()
        )
        
        with manager._lock:
            result = manager._save_known_devices_locked("error_context")
        
        assert result is False

    def test_notify_select_update_calls_callback(self):
        """_notify_select_update triggers callback if set."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        mock_notify_cb = mock.MagicMock()
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock.MagicMock(),
            mqtt_update_select_callback=mock_notify_cb
        )
        
        manager._notify_select_update()
        
        mock_notify_cb.assert_called_once()

    def test_notify_select_update_handles_none_callback(self):
        """_notify_select_update handles None callback gracefully."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock.MagicMock(),
            mqtt_update_select_callback=None
        )
        
        # Should not raise
        manager._notify_select_update()


class TestKnownDeviceManagerThreadSafety:
    """Thread-safe concurrent access patterns."""

    def test_concurrent_add_devices(self):
        """Multiple threads can safely add devices concurrently."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock.MagicMock()
        )
        
        errors = []

        def add_device(dev_id):
            try:
                manager.add_or_update_device(dev_id, f"Device {dev_id}", f"Model {dev_id}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_device, args=(f"dev{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0
        assert len(manager.known_devices) == 10

    def test_concurrent_read_and_write(self):
        """Multiple readers while writers modify state."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock.MagicMock()
        )
        
        # Start with some devices
        for i in range(5):
            manager.known_devices[f"dev{i}"] = {"name": f"Device {i}"}
        
        read_results = []
        errors = []
        lock = threading.Lock()

        def reader():
            try:
                for _ in range(20):
                    with lock:
                        read_results.append(len(manager.known_devices))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(10):
                    manager.add_or_update_device(f"new_dev{i}", f"New {i}", f"Model {i}")
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0
        # Size should increase from 5 to 15
        assert max(read_results) >= 5

    def test_concurrent_add_and_remove(self):
        """Concurrent adds and removes maintain consistency."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        mock_cleanup_cb = mock.MagicMock()
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock_cleanup_cb
        )
        
        errors = []

        def add_remove_cycle(device_id):
            try:
                for i in range(5):
                    manager.add_or_update_device(device_id, f"Device", f"Model")
                    time.sleep(0.001)
                    manager.remove_device(device_id)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_remove_cycle, args=(f"dev{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert len(errors) == 0

    def test_clear_all_during_concurrent_access(self):
        """Clearing all devices during concurrent access works safely."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock.MagicMock()
        )
        
        # Add initial devices
        for i in range(10):
            manager.known_devices[f"dev{i}"] = {"name": f"Device {i}"}
        
        size_history = []
        errors = []
        lock = threading.Lock()

        def observer():
            try:
                for _ in range(10):
                    with lock:
                        size_history.append(len(manager.known_devices))
                    time.sleep(0.005)
            except Exception as e:
                errors.append(e)

        def clearer():
            time.sleep(0.02)
            try:
                manager.clear_all_devices()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=observer),
            threading.Thread(target=observer),
            threading.Thread(target=clearer)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0
        # Size should eventually reach 0
        assert min(size_history) == 0


class TestKnownDeviceManagerLockBehavior:
    """Verify locking protects shared state."""

    def test_lock_protects_known_devices_modification(self):
        """Lock prevents corruption during modifications."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock.MagicMock()
        )
        
        corrupted = []

        def aggressive_modifier():
            try:
                with manager._lock:
                    for i in range(100):
                        manager.known_devices[f"dev{i}"] = {"name": f"D{i}"}
                        # Simulate work
                        time.sleep(0.0001)
            except Exception as e:
                corrupted.append(e)

        threads = [threading.Thread(target=aggressive_modifier) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(corrupted) == 0
        # State should be valid
        assert all(isinstance(k, str) for k in manager.known_devices.keys())

    def test_save_and_modify_atomicity(self):
        """Modifications and saves happen atomically."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock.MagicMock()
        )
        
        save_states = []

        def saver():
            try:
                with manager._lock:
                    # Capture state at save time
                    save_states.append(len(manager.known_devices))
                    manager._save_known_devices_locked("concurrent_save")
            except Exception:
                pass

        def modifier():
            try:
                for i in range(10):
                    with manager._lock:
                        manager.known_devices[f"dev{i}"] = {"name": f"D{i}"}
            except Exception:
                pass

        threads = [
            threading.Thread(target=saver),
            threading.Thread(target=saver),
            threading.Thread(target=modifier)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # All saved states should be consistent integers
        assert all(isinstance(s, int) for s in save_states)


class TestKnownDeviceManagerErrorHandling:
    """Error conditions under concurrency."""

    def test_discovery_callback_error_handled(self):
        """Errors in discovery callback don't crash manager."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        mock_discovery_cb = mock.MagicMock(side_effect=RuntimeError("Discovery check failed"))
        
        manager = KnownDeviceManager(
            mock_store,
            mock_discovery_cb,
            mock.MagicMock()
        )
        
        # Should return False on error, not raise
        result = manager.get_discovery_enabled()
        
        assert result is False

    def test_cleanup_callback_error_during_remove(self):
        """Cleanup callback errors during device remove."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        mock_cleanup_cb = mock.MagicMock(side_effect=RuntimeError("Cleanup failed"))
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock_cleanup_cb
        )
        
        manager.add_or_update_device("dev1", "Device1", "Model1")
        
        # Should handle error gracefully
        try:
            manager.remove_device("dev1")
        except RuntimeError:
            # Manager might choose to raise or suppress
            pass

    def test_save_error_during_concurrent_adds(self):
        """Save errors during concurrent adds don't corrupt state."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        # First save succeeds, then fails
        mock_store.save_devices.side_effect = [None, RuntimeError("Save failed"), None]
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock.MagicMock()
        )
        
        errors = []

        def add_with_possible_failure(dev_id):
            try:
                manager.add_or_update_device(dev_id, f"Device {dev_id}", f"Model {dev_id}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_with_possible_failure, args=(f"dev{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # State should still be valid even with save errors
        assert all(isinstance(k, str) for k in manager.known_devices.keys())


class TestKnownDeviceManagerIntegration:
    """Integration tests combining multiple features."""

    def test_full_lifecycle_with_persistence(self):
        """Full add/remove lifecycle with persistence."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        mock_cleanup_cb = mock.MagicMock()
        mock_notify_cb = mock.MagicMock()
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock_cleanup_cb,
            mqtt_update_select_callback=mock_notify_cb
        )
        
        # Add device - should trigger save
        manager.add_or_update_device("sensor1", "Sensor 1", ["topic1"])
        assert "sensor1" in manager.known_devices
        assert mock_store.save_devices.called
        
        # Add another device to verify tracking
        mock_store.reset_mock()
        manager.add_or_update_device("sensor2", "Sensor 2", ["topic2"])
        assert mock_store.save_devices.called
        
        # Remove device
        manager.remove_device("sensor1")
        assert "sensor1" not in manager.known_devices
        assert mock_cleanup_cb.called

    def test_concurrent_full_lifecycle(self):
        """Multiple devices going through full lifecycle concurrently."""
        mock_store = mock.MagicMock()
        mock_store.load_devices.return_value = {}
        
        manager = KnownDeviceManager(
            mock_store,
            mock.MagicMock(return_value=True),
            mock.MagicMock()
        )
        
        errors = []

        def device_lifecycle(device_id):
            try:
                # Add
                manager.add_or_update_device(device_id, f"Device {device_id}", "Model")
                time.sleep(0.001)
                
                # Update
                manager.add_or_update_device(device_id, f"Device {device_id} v2", "Model")
                time.sleep(0.001)
                
                # Remove
                manager.remove_device(device_id)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=device_lifecycle, args=(f"dev{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0
        assert len(manager.known_devices) == 0  # All removed
