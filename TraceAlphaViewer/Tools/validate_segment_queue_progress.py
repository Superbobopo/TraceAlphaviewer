"""Verifie que les files bornees de segments avancent ensemble."""
from pathlib import Path
from queue import Full, Queue
import sys
import threading
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from Models.group_analysis import _segment_results


class ParallelQueueTests(unittest.TestCase):
    def metadata(self, count=2):
        return {'segments': [{} for _ in range(count)], 'sources': [
            {'filepath': str(APP / f'fictive-{index}.old'), 'name': f'fictive-{index}'}
            for index in range(count)]}

    def test_second_queue_drained_before_first_terminal_and_results_stay_ordered(self):
        self.check_queues(2)

    def test_four_queues_drained_before_first_terminal_and_results_stay_ordered(self):
        self.check_queues(4)

    def check_queues(self, count):
        from Models.resource_policy import Resources, GIB
        second_advanced = threading.Event()
        seen = []
        tasks = []

        class FakeTask:
            def __init__(self, directory, request):
                self.results = Queue(maxsize=4)
                self.finished = threading.Event()
                self.cancelled = threading.Event()
                self.index = request['index']
                tasks.append(self)
                threading.Thread(target=self.run, daemon=True).start()

            def put(self, kind, payload):
                while not self.cancelled.is_set():
                    try:
                        self.results.put((kind, payload), timeout=.05)
                        return True
                    except Full:
                        pass
                return False

            def run(self):
                try:
                    for step in range(12):
                        if not self.put('segment_detail', ('diagnostic', str(self.index), step, 12, 'Collecte')):
                            return
                    if self.index == count - 1:
                        second_advanced.set()
                    waited = second_advanced.wait(2)
                    self.put('segment_result', {'index': self.index, 'both_advanced': waited})
                    self.put('done', {})
                finally:
                    self.finished.set()

            def cancel(self):
                self.cancelled.set()

        with patch('Models.loading_client.WorkerTask', FakeTask), \
             patch('Models.worker_process_tree.own_process_tree'), \
             patch('Models.resource_policy.detect_resources', return_value=Resources(32*GIB, 16*GIB, 16, True)):
            results = list(_segment_results(APP / 'fictive-store', self.metadata(count), None, None, True,
                                           progress_detail=lambda *row: seen.append(row),
                                           resource_policy={'max_workers': count, 'worker_bytes': GIB}))
        self.assertEqual([row['index'] for row in results], list(range(count)))
        self.assertTrue(all(row['both_advanced'] for row in results))
        self.assertEqual({row[1] for row in seen}, {str(i) for i in range(count)})
        self.assertTrue(all(task.finished.is_set() for task in tasks))

    def test_error_cancels_other_segment_before_propagating(self):
        tasks = []

        class FakeTask:
            def __init__(self, directory, request):
                self.results = Queue(maxsize=4)
                self.finished = threading.Event()
                self.cancelled = threading.Event()
                tasks.append(self)
                if request['index'] == 0:
                    self.results.put(('error', 'Erreur fictive du segment'))
                    self.finished.set()

            def cancel(self):
                self.cancelled.set()
                self.finished.set()

        with patch('Models.loading_client.WorkerTask', FakeTask), \
             patch('Models.worker_process_tree.own_process_tree'):
            with self.assertRaisesRegex(OSError, 'Erreur fictive'):
                list(_segment_results(APP / 'fictive-store', self.metadata(), None, None, True))
        self.assertEqual(len(tasks), 2)
        self.assertTrue(tasks[1].cancelled.is_set())
        self.assertTrue(all(task.finished.is_set() for task in tasks))


if __name__ == '__main__':
    unittest.main(verbosity=2)
