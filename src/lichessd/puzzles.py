from __future__ import annotations

import logging
from dataclasses import dataclass
from io import StringIO
from typing import TYPE_CHECKING, Any

import chess
import chess.pgn

if TYPE_CHECKING:
    from lichessd.api import LichessAPI

logger = logging.getLogger(__name__)


async def fetch_puzzle(
    api: LichessAPI,
    angle: str = "mix",
    difficulty: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    result = await api.get_puzzle(angle=angle, difficulty=difficulty, color=color)
    _enrich_puzzle_fen(result)
    return result


def _enrich_puzzle_fen(data: dict[str, Any]) -> None:
    puzzle = data.get("puzzle", {})
    if "fen" in puzzle:
        return

    game = data.get("game", {})
    pgn_text = game.get("pgn", "")

    if not pgn_text:
        return

    try:
        pgn_game = chess.pgn.read_game(StringIO(pgn_text))
        if pgn_game is None:
            return
        board = pgn_game.board()
        moves = list(pgn_game.mainline_moves())
        for move in moves:
            board.push(move)
        puzzle["fen"] = board.fen()
    except Exception:
        logger.debug("Failed to compute puzzle FEN", exc_info=True)


@dataclass
class PuzzleSession:
    puzzle_id: str
    board: chess.Board
    solution: list[str]
    rating: int = 0
    current_index: int = 0
    solved: bool = False


def create_puzzle_session(api_data: dict[str, Any]) -> PuzzleSession | None:
    puzzle = api_data.get("puzzle", {})
    puzzle_id = str(puzzle.get("id", ""))
    solution = puzzle.get("solution", [])
    fen = puzzle.get("fen", "")
    rating = int(puzzle.get("rating", 0))

    if not puzzle_id or not solution or not fen:
        return None

    board = chess.Board(fen)
    return PuzzleSession(
        puzzle_id=puzzle_id,
        board=board,
        solution=[str(m) for m in solution],
        rating=rating,
        current_index=0,
        solved=False,
    )


def validate_puzzle_move(session: PuzzleSession, algebraic_move: str) -> dict[str, object]:
    if session.solved:
        return {"correct": False, "error": "Puzzle already solved", "solved": True}

    if session.current_index >= len(session.solution):
        return {"correct": True, "solved": True, "fen": session.board.fen()}

    try:
        move = session.board.parse_san(algebraic_move)
        uci = move.uci()
    except ValueError:
        return {
            "correct": False,
            "error": f"Invalid move: {algebraic_move}",
            "fen": session.board.fen(),
        }

    expected = session.solution[session.current_index]

    if uci != expected:
        try:
            expected_san = session.board.san(chess.Move.from_uci(expected))
        except Exception:
            expected_san = expected

        return {
            "correct": False,
            "correct_move": expected_san,
            "fen": session.board.fen(),
        }

    session.board.push(move)
    session.current_index += 1

    opponent_san: str | None = None
    if session.current_index < len(session.solution):
        opp_uci = session.solution[session.current_index]
        opp_move = chess.Move.from_uci(opp_uci)
        opponent_san = session.board.san(opp_move)
        session.board.push(opp_move)
        session.current_index += 1

    solved = session.current_index >= len(session.solution)
    if solved:
        session.solved = True

    result: dict[str, object] = {
        "correct": True,
        "fen": session.board.fen(),
        "solved": solved,
        "your_move": algebraic_move,
    }
    if opponent_san:
        result["opponent_move"] = opponent_san
        result["opponent_move_uci"] = opp_uci
    if solved:
        result["rating"] = session.rating
        result["puzzle_id"] = session.puzzle_id

    return result
