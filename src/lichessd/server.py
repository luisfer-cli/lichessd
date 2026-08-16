from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from lichessd.notify import run_hook
from lichessd.protocol import Request, encode_event, encode_message
from lichessd.puzzles import (
    PuzzleSession,
    create_puzzle_session,
    fetch_puzzle,
    validate_puzzle_move,
)

_ANGLE_ROTATION = ["mix", "endgame", "mate", "middlegame", "advantage", "opening", "equality"]

if TYPE_CHECKING:
    from lichessd.games import GameStore

logger = logging.getLogger(__name__)


def _respond(writer: asyncio.StreamWriter, obj: dict[str, object]) -> None:
    writer.write(encode_message(obj).encode())


async def _drain(writer: asyncio.StreamWriter) -> None:
    await writer.drain()


class UnixSocketServer:
    def __init__(
        self,
        socket_path: str,
        game_store: GameStore,
        on_move_command: str | None = None,
        on_game_start_command: str | None = None,
        on_game_finish_command: str | None = None,
        default_angle: str = "mix",
    ) -> None:
        self._socket_path = socket_path
        self._store = game_store
        self._on_move_command = on_move_command
        self._on_game_start_command = on_game_start_command
        self._on_game_finish_command = on_game_finish_command
        self._default_angle = default_angle
        self._clients: dict[asyncio.StreamWriter, set[str] | None] = {}
        self._server: asyncio.Server | None = None
        self._puzzle_session: PuzzleSession | None = None
        self._last_puzzle_id: str | None = None
        self._angle_index = 0

    async def start(self) -> None:
        self._store.on_event = self._broadcast_event
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self._socket_path,
        )
        logger.info("Listening on %s", self._socket_path)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for writer in list(self._clients):
            with contextlib.suppress(Exception):
                writer.close()
        self._clients.clear()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._clients[writer] = None
        peer = writer.get_extra_info("peername", "unknown")
        logger.debug("Client connected: %s", peer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                line_str = line.decode(errors="replace").strip()
                if not line_str:
                    continue
                await self._dispatch(writer, line_str)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Client error", exc_info=True)
        finally:
            self._clients.pop(writer, None)
            with contextlib.suppress(Exception):
                writer.close()
            logger.debug("Client disconnected: %s", peer)

    async def _dispatch(self, writer: asyncio.StreamWriter, raw: str) -> None:
        req = Request.from_json(raw)
        if req is None:
            _respond(writer, {"type": "error", "error": "Invalid JSON or missing cmd"})
            await _drain(writer)
            return

        logger.debug("Command: %s (id=%d)", req.cmd, req.id)
        match req.cmd:
            case "subscribe":
                await self._handle_subscribe(writer, req)
            case "games":
                await self._handle_games(writer, req)
            case "move":
                await self._handle_move(writer, req)
            case "puzzle":
                await self._handle_puzzle(writer, req)
            case "puzzle_move":
                await self._handle_puzzle_move(writer, req)
            case "seek":
                await self._handle_seek(writer, req)
            case "challenge":
                await self._handle_challenge(writer, req)
            case "game":
                await self._handle_game(writer, req)
            case _:
                _respond(
                    writer,
                    {
                        "type": "response",
                        "id": req.id,
                        "ok": False,
                        "error": f"Unknown: {req.cmd}",
                    },
                )
                await _drain(writer)

    async def _handle_subscribe(
        self,
        writer: asyncio.StreamWriter,
        req: Request,
    ) -> None:
        self._clients[writer] = None
        _respond(
            writer,
            {
                "type": "response",
                "id": req.id,
                "ok": True,
                "data": {"message": "Subscribed"},
            },
        )
        await _drain(writer)

    async def _handle_games(
        self,
        writer: asyncio.StreamWriter,
        req: Request,
    ) -> None:
        games = self._store.list_games()
        _respond(
            writer,
            {
                "type": "response",
                "id": req.id,
                "ok": True,
                "data": {"games": games, "count": len(games)},
            },
        )
        await _drain(writer)

    async def _handle_move(
        self,
        writer: asyncio.StreamWriter,
        req: Request,
    ) -> None:
        game_id = req.params.get("game_id")
        move = req.params.get("move")
        if not game_id or not move:
            _respond(
                writer,
                {
                    "type": "response",
                    "id": req.id,
                    "ok": False,
                    "error": "game_id and move required",
                },
            )
            await _drain(writer)
            return

        offering_draw = req.params.get("offering_draw") in (True, "true", "True", "1")
        try:
            result = await self._store.send_move(
                str(game_id),
                str(move),
                offering_draw=offering_draw,
            )
            _respond(
                writer,
                {
                    "type": "response",
                    "id": req.id,
                    "ok": True,
                    "data": result,
                },
            )
        except Exception as e:
            _respond(
                writer,
                {
                    "type": "response",
                    "id": req.id,
                    "ok": False,
                    "error": str(e),
                },
            )
        await _drain(writer)

    async def _handle_puzzle(
        self,
        writer: asyncio.StreamWriter,
        req: Request,
    ) -> None:
        angle = str(req.params.get("angle", self._default_angle))
        difficulty = req.params.get("difficulty")
        color = req.params.get("color")
        try:
            max_attempts = 3
            for attempt in range(max_attempts):
                puzzle = await fetch_puzzle(
                    self._store.api,
                    angle=angle,
                    difficulty=str(difficulty) if difficulty else None,
                    color=str(color) if color else None,
                )
                puzzle_id = str(puzzle.get("puzzle", {}).get("id", ""))
                if puzzle_id != self._last_puzzle_id or attempt == max_attempts - 1:
                    break
                self._angle_index = (self._angle_index + 1) % len(_ANGLE_ROTATION)
                angle = _ANGLE_ROTATION[self._angle_index]

            self._last_puzzle_id = puzzle_id
            session = create_puzzle_session(puzzle)
            if session:
                self._puzzle_session = session
            _respond(
                writer,
                {
                    "type": "response",
                    "id": req.id,
                    "ok": True,
                    "data": puzzle,
                },
            )
        except Exception as e:
            _respond(
                writer,
                {
                    "type": "response",
                    "id": req.id,
                    "ok": False,
                    "error": str(e),
                },
            )
        await _drain(writer)

    async def _handle_puzzle_move(
        self,
        writer: asyncio.StreamWriter,
        req: Request,
    ) -> None:
        move = req.params.get("move")
        if not move:
            _respond(
                writer,
                {
                    "type": "response",
                    "id": req.id,
                    "ok": False,
                    "error": "move required",
                },
            )
            await _drain(writer)
            return

        if not self._puzzle_session:
            _respond(
                writer,
                {
                    "type": "response",
                    "id": req.id,
                    "ok": False,
                    "error": "No active puzzle. Use 'puzzle' command first.",
                },
            )
            await _drain(writer)
            return

        result = validate_puzzle_move(self._puzzle_session, str(move))
        if result.get("solved"):
            self._puzzle_session = None

        _respond(
            writer,
            {
                "type": "response",
                "id": req.id,
                "ok": True,
                "data": result,
            },
        )
        await _drain(writer)

    async def _handle_game(
        self,
        writer: asyncio.StreamWriter,
        req: Request,
    ) -> None:
        game_id = req.params.get("game_id")
        if not game_id:
            _respond(
                writer,
                {
                    "type": "response",
                    "id": req.id,
                    "ok": False,
                    "error": "game_id required",
                },
            )
            await _drain(writer)
            return

        state = self._store.get_game(str(game_id))
        if state is None:
            want_pgn = req.params.get("pgn") in (True, "true", "True", "1")
            try:
                if want_pgn:
                    pgn = await self._store.api.export_game(
                        str(game_id),
                        as_pgn=True,
                    )
                    _respond(
                        writer,
                        {
                            "type": "response",
                            "id": req.id,
                            "ok": True,
                            "data": {"game_id": game_id, "pgn": pgn},
                        },
                    )
                else:
                    data = await self._store.api.export_game(
                        str(game_id),
                        as_pgn=False,
                    )
                    _respond(
                        writer,
                        {
                            "type": "response",
                            "id": req.id,
                            "ok": True,
                            "data": {"game_id": game_id, "game": data},
                        },
                    )
            except Exception as e:
                _respond(
                    writer,
                    {
                        "type": "response",
                        "id": req.id,
                        "ok": False,
                        "error": str(e),
                    },
                )
            await _drain(writer)
            return

        from lichessd.games import _game_state_to_event

        data = _game_state_to_event(state)
        data["moves"] = state.moves

        want_pgn = req.params.get("pgn") in (True, "true", "True", "1")
        if want_pgn:
            try:
                pgn = await self._store.api.export_game(
                    str(game_id),
                    as_pgn=True,
                )
                data["pgn"] = pgn
            except Exception:
                logger.warning("Failed to export PGN for game %s", game_id)

        _respond(
            writer,
            {
                "type": "response",
                "id": req.id,
                "ok": True,
                "data": data,
            },
        )
        await _drain(writer)

    async def _handle_seek(
        self,
        writer: asyncio.StreamWriter,
        req: Request,
    ) -> None:
        days = req.params.get("days")
        rated = req.params.get("rated") in (True, "true", "True", "1")
        variant = str(req.params.get("variant", "standard"))
        rating_range = req.params.get("rating_range")
        color = str(req.params.get("color", "random"))
        try:
            kwargs: dict[str, object] = {"rated": rated, "variant": variant, "color": color}
            if days is not None:
                kwargs["days"] = int(days)
            elif "time" in req.params:
                kwargs["time"] = float(req.params["time"])
                kwargs["increment"] = int(req.params.get("increment", 5))
            else:
                kwargs["days"] = 3
            if rating_range:
                kwargs["rating_range"] = str(rating_range)
            result = await self._store.api.create_seek(**kwargs)  # type: ignore[arg-type]
            _respond(
                writer,
                {
                    "type": "response",
                    "id": req.id,
                    "ok": True,
                    "data": result,
                },
            )
        except Exception as e:
            _respond(
                writer,
                {
                    "type": "response",
                    "id": req.id,
                    "ok": False,
                    "error": str(e),
                },
            )
        await _drain(writer)

    async def _handle_challenge(
        self,
        writer: asyncio.StreamWriter,
        req: Request,
    ) -> None:
        action = str(req.params.get("action", "create"))
        try:
            match action:
                case "create":
                    username = req.params.get("username")
                    if not username:
                        _respond(
                            writer,
                            {
                                "type": "response",
                                "id": req.id,
                                "ok": False,
                                "error": "username required for challenge create",
                            },
                        )
                        await _drain(writer)
                        return
                    days = req.params.get("days")
                    rated = req.params.get("rated") in (True, "true", "True", "1")
                    variant = str(req.params.get("variant", "standard"))
                    color = str(req.params.get("color", "random"))
                    fen = req.params.get("fen")
                    kwargs: dict[str, object] = {
                        "username": str(username),
                        "rated": rated,
                        "variant": variant,
                        "color": color,
                    }
                    if days is not None:
                        kwargs["days"] = int(days)
                    elif "clock_limit" in req.params:
                        kwargs["clock_limit"] = int(req.params["clock_limit"])
                        kwargs["clock_increment"] = int(req.params.get("clock_increment", 5))
                    else:
                        kwargs["days"] = 3
                    if fen:
                        kwargs["fen"] = str(fen)
                    result = await self._store.api.create_challenge(**kwargs)  # type: ignore[arg-type]
                    _respond(
                        writer,
                        {
                            "type": "response",
                            "id": req.id,
                            "ok": True,
                            "data": result,
                        },
                    )
                case "accept":
                    challenge_id = req.params.get("challenge_id")
                    if not challenge_id:
                        _respond(
                            writer,
                            {
                                "type": "response",
                                "id": req.id,
                                "ok": False,
                                "error": "challenge_id required",
                            },
                        )
                        await _drain(writer)
                        return
                    result = await self._store.api.accept_challenge(str(challenge_id))
                    _respond(
                        writer,
                        {
                            "type": "response",
                            "id": req.id,
                            "ok": True,
                            "data": result,
                        },
                    )
                case "decline":
                    challenge_id = req.params.get("challenge_id")
                    if not challenge_id:
                        _respond(
                            writer,
                            {
                                "type": "response",
                                "id": req.id,
                                "ok": False,
                                "error": "challenge_id required",
                            },
                        )
                        await _drain(writer)
                        return
                    reason = str(req.params.get("reason", "generic"))
                    result = await self._store.api.decline_challenge(
                        str(challenge_id),
                        reason=reason,
                    )
                    _respond(
                        writer,
                        {
                            "type": "response",
                            "id": req.id,
                            "ok": True,
                            "data": result,
                        },
                    )
                case _:
                    _respond(
                        writer,
                        {
                            "type": "response",
                            "id": req.id,
                            "ok": False,
                            "error": (
                                f"Unknown challenge action: {action}. Use: create, accept, decline"
                            ),
                        },
                    )
        except Exception as e:
            _respond(
                writer,
                {
                    "type": "response",
                    "id": req.id,
                    "ok": False,
                    "error": str(e),
                },
            )
        await _drain(writer)

    async def _broadcast_event(
        self,
        event_type: str,
        data: dict[str, object],
    ) -> None:
        event_line = encode_event(event_type, **{k: v for k, v in data.items()}) + "\n"
        event_bytes = event_line.encode()

        dead: list[asyncio.StreamWriter] = []
        for writer in self._clients:
            try:
                writer.write(event_bytes)
            except Exception:
                dead.append(writer)

        for writer in dead:
            self._clients.pop(writer, None)

        if self._on_move_command and event_type == "move":
            await run_hook(self._on_move_command, event_type, dict(data))
        if self._on_game_start_command and event_type == "game_start":
            await run_hook(self._on_game_start_command, event_type, dict(data))
        if self._on_game_finish_command and event_type == "game_finish":
            await run_hook(self._on_game_finish_command, event_type, dict(data))
