from __future__ import annotations

import unittest
from typing import Any

import chess

from lichessd.puzzles import (
    PuzzleSession,
    _enrich_puzzle_fen,
    create_puzzle_session,
    validate_puzzle_move,
)


def _api_data(fen: str | None = None, pgn: str | None = None) -> dict[str, Any]:
    puzzle: dict[str, Any] = {
        "id": "p123",
        "solution": ["e2e4", "e7e5", "g1f3"],
        "rating": 1500,
    }
    if fen:
        puzzle["fen"] = fen
    data: dict[str, Any] = {"puzzle": puzzle}
    if pgn:
        data["game"] = {"pgn": pgn}
    return data


class TestCreatePuzzleSession(unittest.TestCase):
    def test_valid(self) -> None:
        session = create_puzzle_session(_api_data(fen=chess.STARTING_FEN))
        assert session is not None
        self.assertEqual(session.puzzle_id, "p123")
        self.assertEqual(session.solution, ["e2e4", "e7e5", "g1f3"])
        self.assertEqual(session.rating, 1500)
        self.assertFalse(session.solved)

    def test_missing_fen_returns_none(self) -> None:
        self.assertIsNone(create_puzzle_session(_api_data(fen="")))

    def test_missing_solution_returns_none(self) -> None:
        data = _api_data(fen=chess.STARTING_FEN)
        data["puzzle"]["solution"] = []
        self.assertIsNone(create_puzzle_session(data))

    def test_missing_id_returns_none(self) -> None:
        data = _api_data(fen=chess.STARTING_FEN)
        data["puzzle"]["id"] = ""
        self.assertIsNone(create_puzzle_session(data))


class TestEnrichPuzzleFen(unittest.TestCase):
    def test_fen_already_present(self) -> None:
        data = _api_data(fen="custom-fen")
        _enrich_puzzle_fen(data)
        self.assertEqual(data["puzzle"]["fen"], "custom-fen")

    def test_computes_fen_from_pgn(self) -> None:
        data = _api_data(pgn="1. e4 e5 2. Nf3")
        _enrich_puzzle_fen(data)
        fen = data["puzzle"]["fen"]
        board = chess.Board(fen)
        self.assertEqual(board.fen(), fen)

    def test_no_pgn_no_change(self) -> None:
        data = _api_data()
        _enrich_puzzle_fen(data)
        self.assertNotIn("fen", data["puzzle"])


class TestValidatePuzzleMove(unittest.TestCase):
    def setUp(self) -> None:
        self.session: PuzzleSession = create_puzzle_session(
            _api_data(fen=chess.STARTING_FEN)
        )  # type: ignore[assignment]

    def test_correct_first_move(self) -> None:
        result = validate_puzzle_move(self.session, "e4")
        self.assertTrue(result["correct"])
        self.assertEqual(result["your_move"], "e4")
        self.assertIn("opponent_move", result)
        self.assertEqual(result["opponent_move_uci"], "e7e5")
        self.assertFalse(result["solved"])

    def test_incorrect_move(self) -> None:
        result = validate_puzzle_move(self.session, "d4")
        self.assertFalse(result["correct"])
        self.assertIn("correct_move", result)

    def test_invalid_move(self) -> None:
        result = validate_puzzle_move(self.session, "zz9")
        self.assertFalse(result["correct"])
        self.assertIn("error", result)

    def test_solve_sequence(self) -> None:
        r1 = validate_puzzle_move(self.session, "e4")
        self.assertFalse(r1["solved"])
        r2 = validate_puzzle_move(self.session, "Nf3")
        self.assertTrue(r2["solved"])
        self.assertEqual(r2.get("puzzle_id"), "p123")
        self.assertEqual(r2.get("rating"), 1500)
        self.assertTrue(self.session.solved)

    def test_move_after_solved(self) -> None:
        validate_puzzle_move(self.session, "e4")
        validate_puzzle_move(self.session, "Nf3")
        result = validate_puzzle_move(self.session, "d4")
        self.assertFalse(result["correct"])
        self.assertIn("already solved", result["error"])


if __name__ == "__main__":
    unittest.main()
