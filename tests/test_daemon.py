from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from lichessd.daemon import check_not_running, write_pid_file


class TestCheckNotRunning(unittest.TestCase):
    def test_no_pid_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            check_not_running(Path(d) / "nope.pid")  # does not raise

    def test_stale_pid_file_with_dead_pid(self) -> None:
        proc = subprocess.Popen(["true"])
        proc.wait()
        with tempfile.TemporaryDirectory() as d:
            pid_file = Path(d) / "lichessd.pid"
            pid_file.write_text(str(proc.pid))
            check_not_running(pid_file)  # does not raise (dead process)

    def test_invalid_pid_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pid_file = Path(d) / "lichessd.pid"
            pid_file.write_text("garbage")
            check_not_running(pid_file)  # does not raise

    def test_live_pid_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pid_file = Path(d) / "lichessd.pid"
            pid_file.write_text(str(os.getpid()))
            with self.assertRaises(SystemExit):
                check_not_running(pid_file)


class TestWritePidFile(unittest.TestCase):
    def test_writes_pid(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pid_file = Path(d) / "sub" / "lichessd.pid"
            write_pid_file(pid_file)
            self.assertEqual(pid_file.read_text(), str(os.getpid()))


if __name__ == "__main__":
    unittest.main()
