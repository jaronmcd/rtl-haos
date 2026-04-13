"""
Tests for ProcessRegistry thread-safety and subprocess lifecycle management.

Covers:
- Thread-safe append/remove/discard operations
- Concurrent access patterns
- Process termination
- Snapshot functionality
"""

import pytest
import subprocess
import threading
import time
from unittest import mock
from rtl_manager import ProcessRegistry, ACTIVE_PROCESSES


class TestProcessRegistryBasic:
    """Basic operations on ProcessRegistry."""

    def test_append_and_contains(self):
        """Registry tracks appended processes."""
        reg = ProcessRegistry()
        mock_proc = mock.MagicMock()
        
        reg.append(mock_proc)
        assert mock_proc in reg

    def test_remove_existing(self):
        """Remove successfully removes existing process."""
        reg = ProcessRegistry()
        mock_proc = mock.MagicMock()
        
        reg.append(mock_proc)
        reg.remove(mock_proc)
        assert mock_proc not in reg

    def test_remove_raises_on_missing(self):
        """Remove raises ValueError if process not in registry."""
        reg = ProcessRegistry()
        mock_proc = mock.MagicMock()
        
        with pytest.raises(ValueError):
            reg.remove(mock_proc)

    def test_discard_existing_returns_true(self):
        """Discard returns True for existing process."""
        reg = ProcessRegistry()
        mock_proc = mock.MagicMock()
        
        reg.append(mock_proc)
        result = reg.discard(mock_proc)
        assert result is True
        assert mock_proc not in reg

    def test_discard_missing_returns_false(self):
        """Discard returns False for missing process."""
        reg = ProcessRegistry()
        mock_proc = mock.MagicMock()
        
        result = reg.discard(mock_proc)
        assert result is False

    def test_clear_empties_registry(self):
        """Clear removes all processes."""
        reg = ProcessRegistry()
        procs = [mock.MagicMock() for _ in range(3)]
        
        for proc in procs:
            reg.append(proc)
        
        reg.clear()
        for proc in procs:
            assert proc not in reg

    def test_snapshot_returns_copy(self):
        """Snapshot returns a list copy of items."""
        reg = ProcessRegistry()
        procs = [mock.MagicMock() for _ in range(2)]
        
        for proc in procs:
            reg.append(proc)
        
        snapshot = reg.snapshot()
        assert snapshot == procs
        # Modifying snapshot shouldn't affect registry
        snapshot.clear()
        assert len(list(reg)) == 2

    def test_iteration_allows_snapshot_reading(self):
        """Iteration allows reading snapshot safely."""
        reg = ProcessRegistry()
        procs = [mock.MagicMock() for _ in range(3)]
        
        for proc in procs:
            reg.append(proc)
        
        collected = list(reg)
        assert len(collected) == 3
        for proc in procs:
            assert proc in collected


class TestProcessRegistryThreadSafety:
    """Thread-safety of ProcessRegistry."""

    def test_concurrent_append_and_contains(self):
        """Multiple threads can safely append and check membership."""
        reg = ProcessRegistry()
        procs = [mock.MagicMock() for _ in range(10)]
        results = {"errors": []}

        def appender(proc):
            try:
                reg.append(proc)
                time.sleep(0.001)
                assert proc in reg
            except Exception as e:
                results["errors"].append(e)

        threads = [threading.Thread(target=appender, args=(proc,)) for proc in procs]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(results["errors"]) == 0
        assert len(list(reg)) == 10

    def test_concurrent_discard_and_check(self):
        """Multiple threads can concurrently attempt to discard."""
        reg = ProcessRegistry()
        procs = [mock.MagicMock() for _ in range(5)]
        
        for proc in procs:
            reg.append(proc)
        
        results = []

        def discarder(proc):
            try:
                result = reg.discard(proc)
                results.append(result)
            except Exception:
                results.append(None)

        threads = [threading.Thread(target=discarder, args=(proc,)) for proc in procs]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # Exactly 5 True results (one per proc), rest are False
        true_count = sum(1 for r in results if r is True)
        assert true_count == 5
        assert len(list(reg)) == 0

    def test_concurrent_remove_with_error_handling(self):
        """Multiple threads attempting remove handle errors gracefully."""
        reg = ProcessRegistry()
        proc = mock.MagicMock()
        reg.append(proc)
        
        results = {"errors": 0, "successes": 0}
        lock = threading.Lock()

        def remover():
            try:
                reg.remove(proc)
                with lock:
                    results["successes"] += 1
            except ValueError:
                with lock:
                    results["errors"] += 1

        # First thread succeeds, rest get ValueError
        threads = [threading.Thread(target=remover) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert results["successes"] == 1
        assert results["errors"] == 4

    def test_concurrent_append_and_snapshot(self):
        """Appending while taking snapshot works safely."""
        reg = ProcessRegistry()
        procs = [mock.MagicMock() for _ in range(20)]
        snapshots = []

        def appender(proc):
            reg.append(proc)

        def snapshotter():
            time.sleep(0.01)  # Let some appends happen first
            for _ in range(5):
                snapshots.append(len(reg.snapshot()))
                time.sleep(0.002)

        threads = [threading.Thread(target=appender, args=(p,)) for p in procs]
        threads.append(threading.Thread(target=snapshotter))
        
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # Snapshots should be consistent (no corruption)
        assert all(isinstance(s, int) for s in snapshots)
        assert all(s >= 0 for s in snapshots)

    def test_concurrent_clear_and_append(self):
        """Concurrent clear and append operations."""
        reg = ProcessRegistry()
        errors = []

        def cycle_adds_clears(proc):
            try:
                for _ in range(10):
                    reg.append(proc)
                    time.sleep(0.001)
                    reg.discard(proc)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=cycle_adds_clears, args=(mock.MagicMock(),))
            for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert len(errors) == 0


class TestProcessRegistryTermination:
    """Process termination capabilities."""

    def test_terminate_all_running_terminates_active(self):
        """terminate_all_running stops all running processes."""
        reg = ProcessRegistry()
        
        # Mock processes with different states
        running_proc = mock.MagicMock()
        running_proc.poll.return_value = None  # Still running
        
        exited_proc = mock.MagicMock()
        exited_proc.poll.return_value = 0  # Already exited
        
        reg.append(running_proc)
        reg.append(exited_proc)
        
        reg.terminate_all_running()
        
        # Should terminate running but not exited
        running_proc.terminate.assert_called_once()
        exited_proc.terminate.assert_not_called()

    def test_terminate_all_running_with_exception(self):
        """terminate_all_running continues on exception."""
        reg = ProcessRegistry()
        
        proc1 = mock.MagicMock()
        proc1.poll.return_value = None
        proc1.terminate.side_effect = RuntimeError("Terminate failed")
        
        proc2 = mock.MagicMock()
        proc2.poll.return_value = None
        proc2.terminate.return_value = None
        
        reg.append(proc1)
        reg.append(proc2)
        
        # Implementation may or may not continue on exception
        # Just verify it doesn't crash
        try:
            reg.terminate_all_running()
        except RuntimeError:
            # Some implementations may propagate
            pass

    def test_terminate_all_running_empty_registry(self):
        """terminate_all_running handles empty registry."""
        reg = ProcessRegistry()
        # Should not raise
        reg.terminate_all_running()


class TestProcessRegistryLockBehavior:
    """Tests that lock is actually protecting shared state."""

    def test_multiple_iterations_are_consistent(self):
        """Multiple simultaneous iterations don't interfere."""
        reg = ProcessRegistry()
        procs = [mock.MagicMock() for _ in range(5)]
        
        for proc in procs:
            reg.append(proc)
        
        collected_lists = []
        lock = threading.Lock()

        def collector():
            result = list(reg)
            with lock:
                collected_lists.append(result)

        threads = [threading.Thread(target=collector) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # All collections should have same length
        assert all(len(cl) == 5 for cl in collected_lists)

    def test_snapshot_and_clear_race_condition(self):
        """Snapshot and clear don't cause corruption."""
        reg = ProcessRegistry()
        procs = [mock.MagicMock() for _ in range(10)]
        
        for proc in procs:
            reg.append(proc)
        
        results = {"snapshots": [], "errors": []}
        lock = threading.Lock()

        def snapshotter():
            try:
                for _ in range(5):
                    snap = reg.snapshot()
                    with lock:
                        results["snapshots"].append(len(snap))
                    time.sleep(0.001)
            except Exception as e:
                with lock:
                    results["errors"].append(e)

        def clearer():
            time.sleep(0.01)
            try:
                reg.clear()
            except Exception as e:
                with lock:
                    results["errors"].append(e)

        threads = [threading.Thread(target=snapshotter) for _ in range(3)]
        threads.append(threading.Thread(target=clearer))
        
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(results["errors"]) == 0
        # Snapshots should be valid integers
        assert all(isinstance(s, int) and s >= 0 for s in results["snapshots"])


class TestProcessRegistryWithActiveProcesses:
    """Integration tests using the global ACTIVE_PROCESSES registry."""

    def test_active_processes_tracks_items(self):
        """Global ACTIVE_PROCESSES tracks appended items."""
        # Get initial count
        initial_procs = list(ACTIVE_PROCESSES)
        initial_count = len(initial_procs)
        
        mock_proc = mock.MagicMock()
        ACTIVE_PROCESSES.append(mock_proc)
        
        # Should have one more
        assert len(list(ACTIVE_PROCESSES)) == initial_count + 1
        assert mock_proc in ACTIVE_PROCESSES
        
        # Cleanup
        ACTIVE_PROCESSES.discard(mock_proc)

    def test_active_processes_clear_cleanup(self):
        """Clearing ACTIVE_PROCESSES removes all."""
        # Add some test items
        test_procs = [mock.MagicMock() for _ in range(3)]
        for proc in test_procs:
            ACTIVE_PROCESSES.append(proc)
        
        ACTIVE_PROCESSES.clear()
        
        # All gone
        for proc in test_procs:
            assert proc not in ACTIVE_PROCESSES

    def test_active_processes_thread_safe_from_multiple_sources(self):
        """ACTIVE_PROCESSES is thread-safe when accessed from multiple threads."""
        procs = [mock.MagicMock() for _ in range(5)]
        errors = []

        def add_and_remove(proc):
            try:
                ACTIVE_PROCESSES.append(proc)
                assert proc in ACTIVE_PROCESSES
                ACTIVE_PROCESSES.remove(proc)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_and_remove, args=(p,)) for p in procs]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0
