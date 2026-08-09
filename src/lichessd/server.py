from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from lichessd.notify import run_hook
from lichessd.protocol import Request, encode_event, encode_message
from lichessd.puzzles import fetch_puzzle

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
        default_angle: str = "mix",
    ) -> None:
        self._socket_path = socket_path
        self._store = game_store
        self._on_move_command = on_move_command
        self._default_angle = default_angle
        self._clients: dict[asyncio.StreamWriter, set[str] | None] = {}
        self._server: asyncio.Server | None = None

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
            puzzle = await fetch_puzzle(
                self._store.api,
                angle=angle,
                difficulty=str(difficulty) if difficulty else None,
                color=str(color) if color else None,
            )
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
            await run_hook(self._on_move_command, dict(data))
