from __future__ import annotations

import os
import signal
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def daemonize(pid_file: Path) -> None:
    """Double-fork daemonization following Unix conventions."""
    if os.fork() > 0:
        sys.exit(0)

    os.setsid()
    os.umask(0o022)

    if os.fork() > 0:
        sys.exit(0)

    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))

    null = os.open(os.devnull, os.O_RDWR)
    os.dup2(null, sys.stdin.fileno())
    os.dup2(null, sys.stdout.fileno())
    os.dup2(null, sys.stderr.fileno())
    os.close(null)

    _install_signal_handlers()


def _install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _handle_exit)
    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


_shutdown_flag = False


def _handle_exit(signum: int, frame: object) -> None:
    global _shutdown_flag
    _shutdown_flag = True


def should_shutdown() -> bool:
    return _shutdown_flag
