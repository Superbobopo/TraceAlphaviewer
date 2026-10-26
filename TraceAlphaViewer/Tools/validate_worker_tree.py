"""Equivalence des segments paralleles et annulation de leurs descendants Windows."""
from pathlib import Path
from dataclasses import asdict
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))
from Models.frame_store import FrameStore, write_frame_store
from Models.group_analysis import analyze_group
from Models.state import BoxInfo, MachineState


@unittest.skipUnless(os.name == 'nt', 'Gestion de processus propre a Windows')
class WorkerTreeTests(unittest.TestCase):
    def test_parallel_matches_serial_and_keeps_reused_identities_separate(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temporary:
            directory = Path(temporary)
            sources = []
            for source_index in range(3):
                path = directory / f'source-{source_index}.old'
                texts = [f'DONNEES FICTIVES {i} C6:1' for i in range(620)]
                path.write_text('\n'.join(texts), encoding='latin-1')
                frames = [MachineState(line_num=i + 1, timestamp=float(i), timestamp_str=f'09:{i//60:02d}:{i%60:02d}',
                    C6=1, raw_lines=[(i + 1, text)],
                    boxes_on_T5=[BoxInfo(id_alpha=1, id_b=1, barcode='3400000000001')] if i >= 3 else [])
                    for i, text in enumerate(texts)]
                store = directory / f'store-{source_index}'
                write_frame_store(frames, store)
                sources.append(dict(filepath=str(path), store=str(store), name=path.name,
                                    start=f'2026-01-0{source_index + 1}T09:00:00'))
            serial = analyze_group(sources, directory / 'serial')
            parallel = analyze_group(sources, directory / 'parallel', parallel=True)
            for key in ('events', 'diagnostics', 'references'):
                self.assertEqual([asdict(row) for row in serial[key]], [asdict(row) for row in parallel[key]])
            self.assertEqual(len(parallel['references']),3)
            with FrameStore(serial['store']) as old, FrameStore(parallel['store']) as new:
                self.assertEqual(list(old),list(new))
                self.assertEqual(old.read_measurements(),new.read_measurements())
                self.assertEqual(old.read_camera_report(),new.read_camera_report())

    def test_terminating_parent_closes_child_process(self):
        import ctypes
        from ctypes import wintypes
        script = (
            'from Models.worker_process_tree import own_process_tree\n'
            'import subprocess,sys,time\n'
            'own_process_tree()\n'
            'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"],'
            'creationflags=subprocess.CREATE_NO_WINDOW)\n'
            'print(child.pid,flush=True)\n'
            'time.sleep(60)\n')
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,wintypes.DWORD]
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE,wintypes.UINT]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        process = subprocess.Popen([sys.executable,'-u','-c',script],cwd=ROOT / 'TraceAlphaViewer',
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        handle = None
        try:
            value = process.stdout.readline().strip()
            self.assertTrue(value.isdigit(),process.stderr.read().decode(errors='replace') if not value else value)
            handle = kernel.OpenProcess(0x101002,False,int(value))
            self.assertTrue(handle)
            process.terminate()
            process.wait(timeout=5)
            self.assertEqual(kernel.WaitForSingleObject(handle,5000),0)
        finally:
            if process.poll() is None:
                process.kill();process.wait(timeout=5)
            if handle:
                if kernel.WaitForSingleObject(handle,0) != 0:
                    kernel.TerminateProcess(handle,1)
                kernel.CloseHandle(handle)
            process.stdout.close();process.stderr.close()


if __name__ == '__main__':
    unittest.main()
