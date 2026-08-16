from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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


@dataclass
class GameStore:
    api: LichessAPI
    on_event: EventCallback | None = None
    _games: dict[str, GameState] = field(default_factory=dict)
    _poll_task: asyncio.Task[None] | None = None
    _events_task: asyncio.Task[None] | None = None
    _stream_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)

    async def _emit(self, event_type: str, data: dict[str, object]) -> None:
        if self.on_event:
            await self.on_event(event_type, data)

    async def _poll_once(self) -> None:
        try:
            result = await self.api.get_playing(nb=20)
        except Exception:
            logger.exception("Failed to poll /api/account/playing")
            return

        now_playing = result.get("nowPlaying", [])
        seen_ids: set[str] = set()

        for entry in now_playing:
            speed = entry.get("speed", "")
            if speed != "correspondence":
                continue

            game_id = entry["gameId"]
            seen_ids.add(game_id)
            full_id = entry.get("fullId", game_id)
            fen = entry.get("fen", "")
            last_move = entry.get("lastMove", "")
            is_my_turn = entry.get("isMyTurn", False)
            color = entry.get("color", "white")
            opponent = entry.get("opponent", {})
            rated = entry.get("rated", False)
            seconds_left = entry.get("secondsLeft", 0)

            new_state = GameState(
                game_id=game_id,
                full_id=full_id,
                fen=fen,
                last_move=last_move,
                is_my_turn=is_my_turn,
                color=color,
                opponent=opponent,
                speed=speed,
                rated=rated,
                seconds_left=seconds_left,
            )

            old_state = self._games.get(game_id)
            self._games[game_id] = new_state

            if old_state is None:
                self._start_stream(game_id)
                await self._emit("game_start", _game_state_to_event(new_state))
            elif old_state.last_move != last_move and last_move:
                await self._emit("move", _game_state_to_event(new_state))

        removed = set(self._games.keys()) - seen_ids
        for game_id in removed:
            state = self._games.pop(game_id, None)
            if state:
                self._stop_stream(game_id)
                await self._emit("game_finish", {"game_id": game_id})

    async def poll_loop(self, interval: float = 30.0) -> None:
        logger.info("Poll loop started (interval=%.1fs)", interval)
        while True:
            await self._poll_once()
            await asyncio.sleep(interval)

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
                    event_type = event.get("type", "")
                    if event_type == "gameStart":
                        game = event.get("game", {})
                        if game.get("speed") == "correspondence":
                            state = GameState(
                                game_id=game.get("gameId", game.get("id", "")),
                                full_id=game.get("fullId", ""),
                                fen=game.get("fen", ""),
                                last_move=game.get("lastMove", ""),
                                is_my_turn=game.get("isMyTurn", False),
                                color=game.get("color", "white"),
                                opponent=game.get("opponent", {}),
                                speed="correspondence",
                                rated=game.get("rated", False),
                                seconds_left=game.get("secondsLeft", 0),
                            )
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

    async def start(self, poll_interval: float = 30.0) -> None:
        try:
            await asyncio.wait_for(self._poll_once(), timeout=10.0)
        except (TimeoutError, Exception):
            logger.warning("Initial poll failed, API may be unreachable")
        self._poll_task = asyncio.create_task(self.poll_loop(poll_interval))
        self._events_task = asyncio.create_task(self._stream_events_loop())

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
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
                    if event.get("type") == "gameState":
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

    async def _handle_game_state(self, game_id: str, event: dict[str, object]) -> None:
        state = self._games.get(game_id)
        if state is None:
            return

        moves = str(event.get("moves", ""))
        move_list = moves.split()
        last_move = move_list[-1] if move_list else ""
        status = event.get("status", "")
        is_finished = status not in ("started", "", None)

        changed = bool(last_move) and state.last_move != last_move
        state.moves = moves
        state.fen = str(event.get("fen", state.fen))
        if changed:
            state.last_move = last_move
            await self._emit("move", _game_state_to_event(state))

        if is_finished:
            self._games.pop(game_id, None)
            winner = event.get("winner", "")
            await self._emit(
                "game_finish",
                {"game_id": game_id, "winner": winner, "status": status},
            )


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
