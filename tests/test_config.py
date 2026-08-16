from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lichessd.config import Config


class TestResolveApiKey(unittest.TestCase):
    def test_cli_key_wins(self) -> None:
        key = Config._resolve_api_key("lip_cli", Path("/nonexistent"))
        self.assertEqual(key, "lip_cli")

    def test_env_key(self) -> None:
        with mock.patch.dict(os.environ, {"LICHESS_API_KEY": "lip_env"}, clear=True):
            key = Config._resolve_api_key(None, Path("/nonexistent"))
            self.assertEqual(key, "lip_env")

    def test_config_file_key_value(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".cfg", delete=False) as f:
            f.write("# comment\napi_key = lip_file\n")
            path = Path(f.name)
        try:
            key = Config._resolve_api_key(None, path)
            self.assertEqual(key, "lip_file")
        finally:
            path.unlink()

    def test_config_file_bare_token(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".cfg", delete=False) as f:
            f.write("lip_bare\n")
            path = Path(f.name)
        try:
            key = Config._resolve_api_key(None, path)
            self.assertEqual(key, "lip_bare")
        finally:
            path.unlink()

    def test_missing_key_raises(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit):
            Config._resolve_api_key(None, Path("/nonexistent/config"))


class TestFromArgs(unittest.TestCase):
    def test_defaults(self) -> None:
        with mock.patch.dict(os.environ, {"LICHESS_API_KEY": "lip_env"}, clear=True):
            cfg = Config.from_args([])
        self.assertEqual(cfg.api_key, "lip_env")
        self.assertEqual(cfg.default_angle, "mix")
        self.assertIsNone(cfg.on_move)

    def test_cli_overrides(self) -> None:
        cfg = Config.from_args(
            [
                "--api-key", "lip_cli",
                "--socket", "/tmp/s.sock",
                "--default-angle", "mateIn2",
                "--on-move", "notify.sh",
            ]
        )
        self.assertEqual(cfg.api_key, "lip_cli")
        self.assertEqual(cfg.socket_path, Path("/tmp/s.sock"))
        self.assertEqual(cfg.default_angle, "mateIn2")
        self.assertEqual(cfg.on_move, "notify.sh")

    def test_daemonize_and_foreground_flags_accepted(self) -> None:
        cfg = Config.from_args(["--api-key", "k", "--daemonize"])
        self.assertTrue(cfg.daemonize)
        self.assertFalse(cfg.foreground)
        cfg = Config.from_args(["--api-key", "k", "--foreground"])
        self.assertTrue(cfg.foreground)
        self.assertFalse(cfg.daemonize)


if __name__ == "__main__":
    unittest.main()
