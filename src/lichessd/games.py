from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lichessd.api import LichessAPI

import chess

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, dict[str, object]], Coroutine[None, None, None]]


@dataclass
class GameState:
    game_id: str
    full_id: str
    fen: str
    last_move: str
    is_my_turn: bool
    color: str
    opponent: dict[str, object]
    speed: str
    rated: bool
    seconds_left: int
    moves: str = ""
    initial_fen: str = ""


@dataclass
class GameStore:
    api: LichessAPI
    on_event: EventCallback | None = None
    _games: dict[str, GameState] = field(default_factory=dict)
    _events_task: asyncio.Task[None] | None = None
    _stream_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)

    async def _emit(self, event_type: str, data: dict[str, object]) -> None:
        if self.on_event:
            await self.on_event(event_type, data)

    async def _initial_sync(self) -> None:
        """Discover correspondence games already in progress and start their streams."""
        try:
            result = await self.api.get_playing(nb=20)
        except Exception:
            logger.exception("Initial sync of /api/account/playing failed")
            return

        for entry in result.get("nowPlaying", []):
            state = _state_from_entry(entry)
            if state is None:
                continue
            self._games[state.game_id] = state
            self._start_stream(state.game_id)
            await self._emit("game_start", _game_state_to_event(state))

    async def _stream_events_loop(self) -> None:
        logger.info("Global event stream started")
        while True:
            try:
                response = await self.api.stream_events()
                if response.status_code in (401, 403):
                    logger.error(
                        "Event stream auth error (%d), retrying in 60s",
                        response.status_code,
                    )
                    await response.aclose()
                    await asyncio.sleep(60)
                    continue
                if response.status_code != 200:
                    logger.warning(
                        "Event stream returned %d, retrying in 30s",
                        response.status_code,
                    )
                    await response.aclose()
                    await asyncio.sleep(30)
                    continue
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    event_type = event.get("type", "")
                    if event_type == "gameStart":
                        game = event.get("game", {})
                        state = _state_from_entry(game) if isinstance(game, dict) else None
                        if state is not None and state.game_id not in self._games:
                            self._games[state.game_id] = state
                            self._start_stream(state.game_id)
                            await self._emit(
                                "game_start",
                                _game_state_to_event(state),
                            )
                    elif event_type == "gameFinish":
                        event_game = event.get("game", {})
                        gid = event_game.get("gameId", event_game.get("id", ""))
                        if gid in self._games:
                            del self._games[gid]
                        self._stop_stream(gid)
                        await self._emit("game_finish", {"game_id": gid})
                logger.warning("Event stream closed, reconnecting in 2s")
                await response.aclose()
                await asyncio.sleep(2)
            except Exception:
                logger.exception("Event stream error, reconnecting in 30s")
                await asyncio.sleep(30)

    async def start(self) -> None:
        try:
            await asyncio.wait_for(self._initial_sync(), timeout=10.0)
        except (TimeoutError, Exception):
            logger.warning("Initial sync failed, API may be unreachable")
        self._events_task = asyncio.create_task(self._stream_events_loop())

    async def stop(self) -> None:
        if self._events_task:
            self._events_task.cancel()
        for task in self._stream_tasks.values():
            task.cancel()
        self._stream_tasks.clear()

    def list_games(self) -> list[dict[str, object]]:
        return [_game_state_to_event(s) for s in self._games.values()]

    def get_game(self, game_id: str) -> GameState | None:
        return self._games.get(game_id)

    async def send_move(
        self,
        game_id: str,
        move: str,
        *,
        offering_draw: bool = False,
    ) -> dict[str, object]:
        uci_move = _try_convert_to_uci(self._games.get(game_id), move)
        return await self.api.make_move(game_id, uci_move, offering_draw=offering_draw)

    def _start_stream(self, game_id: str) -> None:
        if game_id in self._stream_tasks:
            return
        task = asyncio.create_task(self.stream_game(game_id))
        self._stream_tasks[game_id] = task
        task.add_done_callback(lambda _: self._stream_tasks.pop(game_id, None))

    def _stop_stream(self, game_id: str) -> None:
        task = self._stream_tasks.pop(game_id, None)
        if task and not task.done():
            task.cancel()

    async def stream_game(self, game_id: str) -> None:
        while game_id in self._games:
            try:
                response = await self.api.stream_game(game_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Game stream %s error, reconnecting in 5s", game_id)
                await asyncio.sleep(5)
                continue

            try:
                if response.status_code in (401, 403, 404):
                    logger.warning(
                        "Game stream %s ended with status %d",
                        game_id,
                        response.status_code,
                    )
                    await response.aclose()
                    return
                if response.status_code != 200:
                    logger.warning(
                        "Game stream %s returned %d, retrying in 5s",
                        game_id,
                        response.status_code,
                    )
                    await response.aclose()
                    await asyncio.sleep(5)
                    continue
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get("type") in ("gameFull", "gameState"):
                        await self._handle_game_state(game_id, event)
                        if game_id not in self._games:
                            return
                logger.warning("Game stream %s closed, reconnecting in 2s", game_id)
                await response.aclose()
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                await response.aclose()
                raise
            except Exception:
                logger.exception("Game stream %s error, reconnecting in 5s", game_id)
                await asyncio.sleep(5)

    async def _handle_game_state(self, game_id: str, event: dict[str, Any]) -> None:
        state = self._games.get(game_id)
        if state is None:
            return

        moves, status, winner = _extract_game_state(event)
        move_list = moves.split()
        last_move = move_list[-1] if move_list else ""
        is_finished = status not in ("started", "", None)

        if event.get("type") == "gameFull":
            state.initial_fen = str(event.get("initialFen", ""))
        if state.initial_fen and moves:
            state.fen = _compute_fen(state.initial_fen, moves)

        changed = bool(last_move) and state.last_move != last_move
        state.moves = moves
        if changed:
            state.last_move = last_move
            state.is_my_turn = _is_my_turn(state.color, len(move_list))
            await self._emit("move", _game_state_to_event(state))

        if is_finished:
            self._games.pop(game_id, None)
            await self._emit(
                "game_finish",
                {"game_id": game_id, "winner": winner, "status": status},
            )


def _state_from_entry(entry: dict[str, Any]) -> GameState | None:
    if entry.get("speed") != "correspondence":
        return None
    game_id = entry.get("gameId")
    if not game_id:
        return None
    opponent = entry.get("opponent", {})
    if not isinstance(opponent, dict):
        opponent = {}
    return GameState(
        game_id=str(game_id),
        full_id=str(entry.get("fullId", game_id)),
        fen=str(entry.get("fen", "")),
        last_move=str(entry.get("lastMove", "")),
        is_my_turn=bool(entry.get("isMyTurn", False)),
        color=str(entry.get("color", "white")),
        opponent=opponent,
        speed="correspondence",
        rated=bool(entry.get("rated", False)),
        seconds_left=int(entry.get("secondsLeft", 0)),
    )


def _extract_game_state(event: dict[str, Any]) -> tuple[str, str, object]:
    if event.get("type") == "gameFull":
        state = event.get("state", {})
        if isinstance(state, dict):
            return (
                str(state.get("moves", "")),
                str(state.get("status", "")),
                state.get("winner", ""),
            )
    return (
        str(event.get("moves", "")),
        str(event.get("status", "")),
        event.get("winner", ""),
    )


def _compute_fen(initial_fen: str, moves: str) -> str:
    fen = chess.STARTING_FEN if initial_fen == "startpos" else initial_fen
    try:
        board = chess.Board(fen)
        for move in moves.split():
            board.push_uci(move)
        return board.fen()
    except Exception:
        return fen


def _is_my_turn(color: str, num_moves: int) -> bool:
    if color == "white":
        return num_moves % 2 == 0
    return num_moves % 2 == 1


def _try_convert_to_uci(state: GameState | None, move: str) -> str:
    if not state or not state.fen:
        return move

    try:
        board = chess.Board(state.fen)
        chess_move = board.parse_san(move)
        return chess_move.uci()
    except ValueError:
        return move


def _game_state_to_event(state: GameState) -> dict[str, object]:
    return {
        "game_id": state.game_id,
        "full_id": state.full_id,
        "fen": state.fen,
        "last_move": state.last_move,
        "is_my_turn": state.is_my_turn,
        "color": state.color,
        "opponent": state.opponent,
        "rated": state.rated,
        "seconds_left": state.seconds_left,
    }
