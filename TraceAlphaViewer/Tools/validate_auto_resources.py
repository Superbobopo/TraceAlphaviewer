"""Verifie les budgets partages et l'equivalence des diagnostics paralleles."""
from dataclasses import asdict
from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from Models.resource_policy import (Resources, ResourceGovernor, budget_for, cpu_limit,
    execution_policy, get_governor, GIB, MIB)
from Models.frame_store import FrameStore, write_frame_store_iter
from Models.state import MachineState


class ResourceTests(unittest.TestCase):
    def test_profiles_limits_and_unknown_resources(self):
        self.assertEqual(budget_for(Resources()), 0)
        self.assertEqual(cpu_limit(Resources()), 1)
        for total, available, expected in [(4, 2, 0), (8, 4, 2), (16, 8, 4), (32, 16, 8)]:
            value = Resources(total * GIB, available * GIB, 16, True)
            self.assertEqual(budget_for(value), expected * GIB)
            self.assertLessEqual(budget_for(value, 512 * MIB), 512 * MIB)
        for cpus, expected in [(1, 1), (2, 1), (4, 2), (16, 4)]:
            self.assertEqual(cpu_limit(Resources(32 * GIB, 16 * GIB, cpus, True)), expected)
        self.assertEqual(execution_policy(Resources(), 0, candidate=True)['max_workers'], 1)
        with patch('Models.resource_policy.QUALIFIED_FILE_MIN_BYTES', 0), \
             patch('Models.resource_policy.QUALIFIED_FOLDER_WORKERS', 4):
            big = Resources(32 * GIB, 16 * GIB, 16, True)
            self.assertEqual(execution_policy(big, 8 * GIB)['max_workers'], 4)
            self.assertEqual(execution_policy(big, GIB)['max_workers'], 1)
            self.assertEqual(execution_policy(Resources(16 * GIB, 8 * GIB, 5, True),
                4 * GIB, 'folder_group')['max_workers'], 2)

    def test_pressure_reduces_future_launches_without_revoking_active_work(self):
        current = [Resources(32 * GIB, 16 * GIB, 16, True)]
        governor = ResourceGovernor(lambda: current[0], monitor=False)
        with patch('Models.resource_policy.QUALIFIED_FILE_MIN_BYTES', 0):
            lease, policy = governor.reserve({'mode': 'file'})
        self.assertEqual(policy['max_workers'], 4)
        current[0] = Resources(32 * GIB, GIB, 16, True)
        governor.refresh()
        self.assertIn(lease, governor._leases)
        governor.release(lease)
        next_lease, next_policy = governor.reserve({'mode': 'file'})
        self.assertEqual(next_policy['max_workers'], 1)
        self.assertEqual(next_policy['budget_bytes'], 0)
        governor.release(next_lease)

    def test_shared_workers_reservation_and_cancellation(self):
        resources = Resources(32 * GIB, 16 * GIB, 16, True)
        governor = ResourceGovernor(lambda: resources, monitor=False)
        with patch('Models.resource_policy.QUALIFIED_FILE_MIN_BYTES', 0):
            lease, policy = governor.reserve({'mode': 'file', 'path': 'absent'})
        self.assertEqual(policy['max_workers'], 4)
        cancel = threading.Event()
        observed = []
        def pending():
            try:
                governor.reserve({'mode': 'file'}, cancel)
            except InterruptedError:
                observed.append('annule')
        thread = threading.Thread(target=pending)
        thread.start()
        cancel.set()
        thread.join(2)
        self.assertEqual(observed, ['annule'])
        governor.release(lease)
        self.assertFalse(governor._leases)

    def test_cache_hits_budget_pressure_and_release(self):
        current = [Resources(32 * GIB, 16 * GIB, 16, True)]
        governor = ResourceGovernor(lambda: current[0], monitor=False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_frame_store_iter((MachineState(line_num=i + 1, timestamp=i,
                raw_lines=[(i + 1, 'Ligne fictive ' + str(i), False)]) for i in range(6000)), path)
            with FrameStore(path, cache_governor=governor) as frames, FrameStore(path) as reference:
                for index in range(0, 6000, 500):
                    self.assertEqual(frames[index], reference[index])
                self.assertGreater(len(frames._cache), 2)
                misses = frames.cache_misses
                self.assertEqual(frames[0], reference[0])
                self.assertEqual(frames.cache_misses, misses)
                self.assertLessEqual(sum(governor._caches.values()), governor.budget)
                current[0] = Resources(32 * GIB, GIB, 16, True)
                governor.refresh()
                self.assertLessEqual(len(frames._cache), 2)
                self.assertEqual(sum(governor._caches.values()), 0)
            self.assertFalse(governor._caches)

    def test_sessions_share_and_release_their_budget(self):
        from Models.loading_client import LoadingSession
        resources = Resources(16 * GIB, 8 * GIB, 16, True)
        governor = ResourceGovernor(lambda: resources, limit=512 * MIB, monitor=False)
        class Cache:
            pass
        left, right = Cache(), Cache()
        first = LoadingSession(resource_governor=governor)
        second = LoadingSession(resource_governor=governor)
        try:
            self.assertEqual(governor._owners, 2)
            total = governor.cache_allowance(left, GIB) + governor.cache_allowance(right, GIB)
            self.assertLessEqual(total, governor.budget)
            self.assertLessEqual(total, 512 * MIB)
            governor.release_cache(left)
            self.assertNotIn(left, governor._caches)
            first.close()
            self.assertEqual(governor._owners, 1)
            self.assertFalse(second.closed.is_set())
        finally:
            first.close()
            second.close()
            self.assertTrue(first.cleaned.wait(5))
            self.assertTrue(second.cleaned.wait(5))
        self.assertEqual(governor._owners, 0)

    def test_folder_quota_matches_segment_count(self):
        governor = ResourceGovernor(lambda: Resources(32 * GIB, 16 * GIB, 16, True), monitor=False)
        for count, expected in [(1, 1), (2, 2), (3, 2), (4, 4)]:
            lease, policy = governor.reserve({'mode': 'folder_group',
                'group': {'sources': [{'bytes': 1024} for _ in range(count)]}})
            self.assertEqual(policy['max_workers'], expected)
            governor.release(lease)

    def test_legacy_settings_are_ignored_without_writes(self):
        from Models.loading_client import LoadingSession
        resources = Resources(32 * GIB, 16 * GIB, 16, True)
        for saved_limit in (512 * MIB, 2 * GIB):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'TraceAlphaViewer' / 'settings.json'
                path.parent.mkdir()
                path.write_text(json.dumps({'version': 1,
                    'acceleration_memory_limit': saved_limit}), encoding='utf-8')
                original = path.read_bytes()
                with patch.dict('os.environ', LOCALAPPDATA=directory), \
                     patch('Models.resource_policy._governor', None), \
                     patch('Models.resource_policy.ResourceGovernor',
                           side_effect=lambda: ResourceGovernor(lambda: resources, monitor=False)):
                    governor = get_governor()
                    self.assertIsNone(governor.limit)
                    self.assertEqual(governor.budget, 8 * GIB)
                    for _ in range(2):
                        session = LoadingSession()
                        try:
                            self.assertIs(session._resource_governor, governor)
                            self.assertIsNone(governor.limit)
                        finally:
                            session.close()
                            self.assertTrue(session.cleaned.wait(5))
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(list(path.parent.iterdir()), [path])


class ParallelTests(unittest.TestCase):
    def test_pressure_before_launch_keeps_families_in_parent(self):
        from Models.diagnostic_parallel import DiagnosticExecution
        with tempfile.TemporaryDirectory() as directory, \
             patch('Models.resource_policy.detect_resources', return_value=Resources()), \
             patch('Models.loading_client.WorkerTask', side_effect=AssertionError('Lancement interdit')), \
             patch('Models.diagnostic_parallel.analyze_family', side_effect=lambda group, *_: {group: []}) as family:
            with DiagnosticExecution([], None, directory, {'max_workers': 4}) as execution:
                result = execution.finish()
                self.assertEqual(set(result), {'signals', 'c5', 'communication'})
                self.assertEqual(family.call_count, 3)
                self.assertFalse(execution.projection.exists())
    @unittest.skipUnless(sys.platform == 'win32', 'Job Object Windows')
    def test_parent_termination_kills_descendant(self):
        import ctypes
        from ctypes import wintypes
        import subprocess
        code = ('from Models.worker_process_tree import own_process_tree; '
                'import subprocess,sys,time; own_process_tree(); '
                'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"],'
                'creationflags=subprocess.CREATE_NO_WINDOW); '
                'print(child.pid,flush=True); time.sleep(60)')
        parent = subprocess.Popen([sys.executable, '-u', '-c', code], cwd=APP,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        handle = None
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        try:
            line = parent.stdout.readline()
            self.assertTrue(line, parent.stderr.read() if parent.poll() is not None else b'PID absent')
            handle = kernel.OpenProcess(0x100000, False, int(line))
            self.assertTrue(handle)
            parent.terminate()
            parent.wait(5)
            self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
        finally:
            if parent.poll() is None:
                parent.terminate()
                parent.wait(5)
            if handle:
                kernel.CloseHandle(handle)
            parent.stdout.close()
            parent.stderr.close()

    def test_projection_roundtrip_and_versions(self):
        from Models.diagnostic import DiagnosticState
        from Models.diagnostic_parallel import pack_projection, unpack_projection
        from Models.loading_worker import run
        import pickle
        state = DiagnosticState(86399.25, '23:59:59.250', True)
        rows = [(1, 'C5:1', state), (2, 'C6:1', state),
                (3, 'Redemarrage', DiagnosticState(86400.5, '00:00:00.500', False))]
        self.assertEqual(rows, list(unpack_projection(pack_projection(rows))))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'projection.pkl'
            path.write_bytes(pickle.dumps((999, None, [])))
            with self.assertRaisesRegex(OSError, 'incompatible'):
                run({'mode': 'diagnostic_family', 'projection': str(path)}, lambda *_: None)

    def test_subprocess_cancellation_and_failure(self):
        from Models.diagnostic_parallel import DiagnosticExecution
        from Models.loading_client import WorkerTask
        from queue import Empty
        import time
        with tempfile.TemporaryDirectory() as directory:
            execution = DiagnosticExecution([], None, directory, {'max_workers': 4})
            with execution:
                tasks = [item['task'] for item in execution.tasks]
            self.assertTrue(all(task.finished.is_set() for task in tasks))
            self.assertTrue(all(task.process is None or task.process.poll() is not None for task in tasks))
            self.assertFalse(execution.projection.exists())
            task = WorkerTask(Path(directory) / 'error', {'mode': 'diagnostic_family',
                'projection': str(Path(directory) / 'absent'), 'family': 'c5'})
            deadline = time.monotonic() + 10
            error = None
            while time.monotonic() < deadline:
                try:
                    kind, payload = task.results.get(timeout=.1)
                except Empty:
                    continue
                if kind == 'error':
                    error = payload
                    break
            self.assertIsNotNone(error)
            self.assertTrue(task.finished.wait(5))

    def test_diagnostics_camera_metadata_and_progress_are_identical(self):
        self.check_diagnostics()

    def test_pressure_fallback_preserves_all_diagnostics(self):
        with patch('Models.resource_policy.detect_resources', return_value=Resources()):
            self.check_diagnostics()

    def check_diagnostics(self):
        from Models import diagnostic
        from Models.diagnostic_parallel import DiagnosticExecution
        from Tools.validate_reference_absent import cycle_lines, frames_for
        frames = frames_for(cycle_lines(1, known=True) + cycle_lines(2, recovered=True) + [
            'tEA-T3: demande le transfert de EA->T3', 'tT3/T4: ERREUR-TRSF-T3-T4 eT4:-47'])
        def lines():
            return diagnostic.TraceLines((number, text, diagnostic.DiagnosticState(
                frame.timestamp, frame.timestamp_str, frame.C6))
                for frame in frames for number, text, *_ in frame.raw_lines)
        before_camera, after_camera, before_metadata, after_metadata, progress = {}, {}, {}, {}, []
        before = diagnostic.build_diagnostics(frames, [], line_states=lines(),
            camera_report_output=before_camera, trace_metadata_output=before_metadata)
        with tempfile.TemporaryDirectory() as directory:
            projection = lines()
            with DiagnosticExecution(projection, None, directory, {'max_workers': 4}) as execution:
                after = diagnostic.build_diagnostics(frames, [], line_states=projection,
                    camera_report_output=after_camera, trace_metadata_output=after_metadata,
                    parallel_execution=execution,
                    progress_cb=lambda name, done, total: progress.append(done / total))
            self.assertFalse(list(Path(directory).rglob('projection.pkl')))
        self.assertEqual([asdict(item) for item in after], [asdict(item) for item in before])
        self.assertEqual(after_camera, before_camera)
        self.assertEqual(after_metadata, before_metadata)
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
