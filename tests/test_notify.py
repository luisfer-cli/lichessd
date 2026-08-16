from __future__ import annotations

import os
import unittest
from unittest import mock

from lichessd.notify import _build_env, _render_command, sh_quote


class TestShQuote(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(sh_quote(""), "''")

    def test_simple(self) -> None:
        self.assertEqual(sh_quote("e2e4"), "'e2e4'")

    def test_with_single_quote(self) -> None:
        self.assertEqual(sh_quote("it's"), "'it'\\''s'")


class TestRenderCommand(unittest.TestCase):
    def test_args_order(self) -> None:
        data = {
            "game_id": "abc",
            "last_move": "e7e5",
            "fen": "rnbq...",
            "color": "white",
            "is_my_turn": True,
        }
        rendered = _render_command("notify.sh", data)
        self.assertEqual(
            rendered,
            "notify.sh 'abc' 'e7e5' 'rnbq...' 'white' 'True'",
        )

    def test_missing_keys_default_to_empty(self) -> None:
        rendered = _render_command("cmd", {})
        self.assertEqual(rendered, "cmd '' '' '' '' ''")


class TestBuildEnv(unittest.TestCase):
    def test_env_vars(self) -> None:
        data = {
            "game_id": "abc",
            "full_id": "abcX",
            "fen": "fen",
            "last_move": "e7e5",
            "is_my_turn": True,
            "color": "white",
            "opponent": {"username": "Juan", "id": "juan"},
            "seconds_left": 100,
        }
        with mock.patch.dict(os.environ, {}, clear=True):
            env = _build_env("move", data)
        self.assertEqual(env["LICHESSD_EVENT"], "move")
        self.assertEqual(env["LICHESSD_GAME_ID"], "abc")
        self.assertEqual(env["LICHESSD_FULL_ID"], "abcX")
        self.assertEqual(env["LICHESSD_FEN"], "fen")
        self.assertEqual(env["LICHESSD_LAST_MOVE"], "e7e5")
        self.assertEqual(env["LICHESSD_IS_MY_TURN"], "True")
        self.assertEqual(env["LICHESSD_COLOR"], "white")
        self.assertEqual(env["LICHESSD_OPPONENT_USERNAME"], "Juan")
        self.assertEqual(env["LICHESSD_OPPONENT_ID"], "juan")
        self.assertEqual(env["LICHESSD_SECONDS_LEFT"], "100")

    def test_env_opponent_missing_defaults_empty(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            env = _build_env("game_finish", {"game_id": "abc"})
        self.assertEqual(env["LICHESSD_OPPONENT_USERNAME"], "")
        self.assertEqual(env["LICHESSD_OPPONENT_ID"], "")


if __name__ == "__main__":
    unittest.main()
