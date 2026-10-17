from __future__ import annotations

import os
import signal
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def check_not_running(pid_file: Path) -> None:
    """Refuse to start if another instance is already running."""
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return
    if pid <= 0:
        return
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return  # stale PID file left by a crashed instance
    except PermissionError:
        pass
    raise SystemExit(
        f"lichessd is already running (PID {pid}). Stop it or remove {pid_file}."
    )


def write_pid_file(pid_file: Path) -> None:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))


def daemonize(pid_file: Path) -> None:
    """Double-fork daemonization following Unix conventions."""
    if os.fork() > 0:
        sys.exit(0)

    os.setsid()
    os.umask(0o022)

    if os.fork() > 0:
        sys.exit(0)

    write_pid_file(pid_file)

    null = os.open(os.devnull, os.O_RDWR)
    os.dup2(null, sys.stdin.fileno())
    os.dup2(null, sys.stdout.fileno())
    os.dup2(null, sys.stderr.fileno())
    os.close(null)

    install_signal_handlers()


def install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _handle_exit)
    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)


_shutdown_flag = False


def _handle_exit(signum: int, frame: object) -> None:
    global _shutdown_flag
    _shutdown_flag = True


def should_shutdown() -> bool:
    return _shutdown_flag
