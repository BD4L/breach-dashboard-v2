"""Deadline cleanup must include browsers detached from the worker group."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from ingestion.models import SourceError
from ingestion.process_tree import owned_processes, terminate_tree
from ingestion.runner import supervise


def running(pid):
    result = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                            capture_output=True, text=True, timeout=2)
    # A terminated orphan can remain briefly as a zombie until init reaps it.
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith('Z')


@unittest.skipUnless(os.name == 'posix', 'POSIX detached process-group regression')
class ProcessTreeTests(unittest.TestCase):
    def test_snapshot_selects_descendants_without_neighboring_processes(self):
        rows = {10: (1, 10), 11: (10, 10), 12: (11, 12), 13: (12, 12),
                20: (1, 20), 21: (20, 20)}
        self.assertEqual(set(owned_processes(rows, 10)), {10, 11, 12, 13})
        self.assertEqual(owned_processes(rows, 999), {})

    def test_cannot_terminate_caller_or_special_process_ids(self):
        for pid in (0, 1, -1, True, os.getpid()):
            with self.assertRaises(ValueError):
                terminate_tree(pid)

    def test_hard_deadline_kills_detached_grandchild_that_ignores_term(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'owned-process.json'
            grandchild = (
                'import json,os,pathlib,signal,sys,time; '
                'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                'pathlib.Path(sys.argv[1]).write_text(json.dumps('
                '{"grandchild":os.getpid(),"worker":os.getppid()})); '
                'time.sleep(60)'
            )
            worker = (
                'import subprocess,sys,time; '
                f'subprocess.Popen([sys.executable,"-c",{grandchild!r},sys.argv[1]],start_new_session=True); '
                'time.sleep(60)'
            )
            started = time.monotonic()
            try:
                with self.assertRaisesRegex(SourceError, 'hard deadline'):
                    supervise([sys.executable, '-c', worker, str(marker)], timeout=1.5)
                self.assertTrue(marker.exists(), 'Detached grandchild never started; cleanup was not exercised')
                captured = json.loads(marker.read_text())
                self.assertFalse(running(captured['worker']))
                self.assertFalse(running(captured['grandchild']), 'Detached browser-like grandchild survived the deadline')
                self.assertLess(time.monotonic() - started, 4)
            finally:
                if marker.exists():
                    for pid in json.loads(marker.read_text()).values():
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass


if __name__ == '__main__':
    unittest.main()
