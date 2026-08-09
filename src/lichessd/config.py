from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Config:
    api_key: str
    socket_path: Path = field(default_factory=lambda: Path.home() / ".lichessd" / "socket")
    pid_file: Path = field(default_factory=lambda: Path.home() / ".lichessd" / "lichessd.pid")
    config_path: Path = field(default_factory=lambda: Path.home() / ".lichessd" / "config")
    on_move: str | None = None
    poll_interval: float = 30.0
    default_angle: str = "mix"

    @classmethod
    def from_args(cls, argv: list[str] | None = None) -> Config:
        parser = argparse.ArgumentParser(
            prog="lichessd",
            description="Unix daemon for Lichess correspondence chess",
        )
        parser.add_argument(
            "--api-key",
            default=None,
            help="Lichess API token (overrides config file and env var)",
        )
        parser.add_argument(
            "--config",
            default=str(Path.home() / ".lichessd" / "config"),
            dest="config_path",
            help="Path to config file (default: ~/.lichessd/config)",
        )
        parser.add_argument(
            "--socket",
            default=str(Path.home() / ".lichessd" / "socket"),
            dest="socket_path",
            help="Unix socket path (default: ~/.lichessd/socket)",
        )
        parser.add_argument(
            "--pid-file",
            default=str(Path.home() / ".lichessd" / "lichessd.pid"),
            dest="pid_file",
            help="PID file path (default: ~/.lichessd/lichessd.pid)",
        )
        parser.add_argument(
            "--on-move",
            default=None,
            dest="on_move",
            metavar="COMMAND",
            help="Command to run when a new move is detected",
        )
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=30.0,
            help="Seconds between game state polls (default: 30)",
        )
        parser.add_argument(
            "--default-angle",
            default="mix",
            help="Default puzzle theme (default: mix)",
        )
        parser.add_argument(
            "--daemonize",
            "-d",
            action="store_true",
            default=False,
            help="Daemonize after startup",
        )
        parser.add_argument(
            "--foreground",
            "-f",
            action="store_true",
            default=False,
            help="Run in foreground (default without -d)",
        )
        args = parser.parse_args(argv)

        api_key = cls._resolve_api_key(
            args.api_key,
            Path(args.config_path),
        )

        return cls(
            api_key=api_key,
            socket_path=Path(args.socket_path),
            pid_file=Path(args.pid_file),
            config_path=Path(args.config_path),
            on_move=args.on_move,
            poll_interval=args.poll_interval,
            default_angle=args.default_angle,
        )

    @staticmethod
    def _resolve_api_key(cli_key: str | None, config_path: Path) -> str:
        if cli_key:
            return cli_key
        key = os.environ.get("LICHESS_API_KEY")
        if key:
            return key
        if config_path.is_file():
            content = config_path.read_text().strip()
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip().upper() == "API_KEY":
                        return v.strip().strip('"').strip("'")
                elif not line.startswith("["):
                    return line.strip().strip('"').strip("'")
        msg = (
            "No API key found. Set it via:\n"
            "  - LICHESS_API_KEY environment variable\n"
            "  - ~/.lichessd/config file (api_key=lip_...)\n"
            "  - --api-key CLI argument"
        )
        raise SystemExit(msg)
