from __future__ import annotations

import unittest

import chess

from lichessd.games import GameState, _game_state_to_event, _try_convert_to_uci


def _state(fen: str = chess.STARTING_FEN, last_move: str = "") -> GameState:
    return GameState(
        game_id="abc",
        full_id="abcX",
        fen=fen,
        last_move=last_move,
        is_my_turn=True,
        color="white",
        opponent={"id": "juan", "username": "Juan"},
        speed="correspondence",
        rated=True,
        seconds_left=100,
    )


class TestTryConvertToUci(unittest.TestCase):
    def test_no_state_returns_move(self) -> None:
        self.assertEqual(_try_convert_to_uci(None, "e2e4"), "e2e4")

    def test_no_fen_returns_move(self) -> None:
        self.assertEqual(_try_convert_to_uci(_state(fen=""), "e2e4"), "e2e4")

    def test_uci_passthrough(self) -> None:
        self.assertEqual(_try_convert_to_uci(_state(), "e2e4"), "e2e4")

    def test_san_conversion(self) -> None:
        self.assertEqual(_try_convert_to_uci(_state(), "e4"), "e2e4")

    def test_invalid_move_returns_original(self) -> None:
        self.assertEqual(_try_convert_to_uci(_state(), "zz9"), "zz9")


class TestGameStateToEvent(unittest.TestCase):
    def test_event_shape(self) -> None:
        event = _game_state_to_event(_state(last_move="e7e5"))
        self.assertEqual(event["game_id"], "abc")
        self.assertEqual(event["full_id"], "abcX")
        self.assertEqual(event["last_move"], "e7e5")
        self.assertEqual(event["is_my_turn"], True)
        self.assertEqual(event["color"], "white")
        self.assertEqual(event["opponent"], {"id": "juan", "username": "Juan"})
        self.assertEqual(event["rated"], True)
        self.assertEqual(event["seconds_left"], 100)
        self.assertEqual(set(event), {
            "game_id", "full_id", "fen", "last_move", "is_my_turn",
            "color", "opponent", "rated", "seconds_left",
        })


if __name__ == "__main__":
    unittest.main()
