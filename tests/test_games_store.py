from __future__ import annotations

import unittest
from typing import Any

import chess

from lichessd.games import GameState, GameStore


class FakeStreamResponse:
    def __init__(self, status_code: int = 200, lines: list[str] | None = None) -> None:
        self.status_code = status_code
        self._lines = lines or []
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeAPI:
    def __init__(self, playing: list[dict[str, Any]] | None = None) -> None:
        self.playing = playing if playing is not None else []
        self.moves: list[dict[str, Any]] = []
        self.stream_responses: list[FakeStreamResponse] = []

    async def get_playing(self, nb: int = 20) -> dict[str, Any]:
        return {"nowPlaying": self.playing}

    async def make_move(
        self, game_id: str, move: str, *, offering_draw: bool = False
    ) -> dict[str, Any]:
        self.moves.append({"game_id": game_id, "move": move, "offering_draw": offering_draw})
        return {"ok": True}

    async def stream_game(self, game_id: str) -> FakeStreamResponse:
        if self.stream_responses:
            return self.stream_responses.pop(0)
        return FakeStreamResponse(status_code=404)


def _entry(game_id: str, last_move: str) -> dict[str, Any]:
    return {
        "gameId": game_id,
        "fullId": f"{game_id}full",
        "fen": chess.STARTING_FEN,
        "lastMove": last_move,
        "isMyTurn": True,
        "color": "white",
        "opponent": {"id": "juan", "username": "Juan"},
        "rated": True,
        "secondsLeft": 100,
        "speed": "correspondence",
    }


class TestPollOnce(unittest.IsolatedAsyncioTestCase):
    async def test_lifecycle_events(self) -> None:
        api = FakeAPI()
        store = GameStore(api=api)
        events: list[tuple[str, dict[str, object]]] = []

        async def on_event(event_type: str, data: dict[str, object]) -> None:
            events.append((event_type, data))

        store.on_event = on_event

        api.playing = [_entry("g1", "")]
        await store._poll_once()
        self.assertEqual([e[0] for e in events], ["game_start"])
        self.assertEqual(events[0][1]["game_id"], "g1")

        api.playing = [_entry("g1", "e7e5")]
        await store._poll_once()
        self.assertEqual([e[0] for e in events], ["game_start", "move"])
        self.assertEqual(events[1][1]["last_move"], "e7e5")

        api.playing = []
        await store._poll_once()
        self.assertEqual([e[0] for e in events], ["game_start", "move", "game_finish"])
        self.assertEqual(events[2][1]["game_id"], "g1")

    async def test_skips_non_correspondence(self) -> None:
        entry = _entry("g1", "")
        entry["speed"] = "blitz"
        api = FakeAPI(playing=[entry])
        store = GameStore(api=api)
        events: list[str] = []
        store.on_event = lambda et, d: events.append(et)  # type: ignore[assignment]
        await store._poll_once()
        self.assertEqual(events, [])
        self.assertEqual(store.list_games(), [])

    async def test_poll_failure_is_swallowed(self) -> None:
        class BrokenAPI:
            async def get_playing(self, nb: int = 20) -> dict[str, Any]:
                raise RuntimeError("boom")

        store = GameStore(api=BrokenAPI())  # type: ignore[arg-type]
        await store._poll_once()  # should not raise


class TestSendMove(unittest.IsolatedAsyncioTestCase):
    async def test_san_converted_to_uci(self) -> None:
        api = FakeAPI()
        store = GameStore(api=api)
        store._games["g1"] = GameState(
            game_id="g1",
            full_id="g1full",
            fen=chess.STARTING_FEN,
            last_move="",
            is_my_turn=True,
            color="white",
            opponent={},
            speed="correspondence",
            rated=True,
            seconds_left=100,
        )
        await store.send_move("g1", "e4")
        self.assertEqual(api.moves[0]["move"], "e2e4")

    async def test_unknown_game_passthrough(self) -> None:
        api = FakeAPI()
        store = GameStore(api=api)
        await store.send_move("g1", "e2e4")
        self.assertEqual(api.moves[0]["move"], "e2e4")

    async def test_offering_draw_forwarded(self) -> None:
        api = FakeAPI()
        store = GameStore(api=api)
        await store.send_move("g1", "e2e4", offering_draw=True)
        self.assertTrue(api.moves[0]["offering_draw"])


def _store_with_game(api: FakeAPI, last_move: str = "") -> GameStore:
    store = GameStore(api=api)
    store._games["g1"] = GameState(
        game_id="g1",
        full_id="g1full",
        fen=chess.STARTING_FEN,
        last_move=last_move,
        is_my_turn=True,
        color="white",
        opponent={},
        speed="correspondence",
        rated=True,
        seconds_left=100,
    )
    return store


class TestStreamGame(unittest.IsolatedAsyncioTestCase):
    async def test_stream_detects_move(self) -> None:
        api = FakeAPI()
        api.stream_responses = [
            FakeStreamResponse(
                200,
                ['{"type": "gameState", "moves": "e2e4 e7e5", "status": "started"}'],
            ),
            FakeStreamResponse(404),
        ]
        store = _store_with_game(api)
        events: list[tuple[str, dict[str, object]]] = []

        async def on_event(event_type: str, data: dict[str, object]) -> None:
            events.append((event_type, data))

        store.on_event = on_event
        await store.stream_game("g1")
        self.assertEqual([e[0] for e in events], ["move"])
        self.assertEqual(events[0][1]["last_move"], "e7e5")

    async def test_stream_emits_finish_and_removes_game(self) -> None:
        api = FakeAPI()
        api.stream_responses = [
            FakeStreamResponse(
                200,
                ['{"type": "gameState", "moves": "e2e4 e7e5", "status": "mate"}'],
            ),
        ]
        store = _store_with_game(api)
        events: list[tuple[str, dict[str, object]]] = []

        async def on_event(event_type: str, data: dict[str, object]) -> None:
            events.append((event_type, data))

        store.on_event = on_event
        await store.stream_game("g1")
        self.assertEqual([e[0] for e in events], ["move", "game_finish"])
        self.assertNotIn("g1", store._games)
        self.assertEqual(events[1][1]["game_id"], "g1")

    async def test_start_stream_on_poll_game_start(self) -> None:
        api = FakeAPI(playing=[_entry("g1", "")])
        store = GameStore(api=api)

        async def on_event(event_type: str, data: dict[str, object]) -> None:
            pass

        store.on_event = on_event
        await store._poll_once()
        self.assertIn("g1", store._stream_tasks)
        await store._stream_tasks["g1"]
        self.assertNotIn("g1", store._stream_tasks)


if __name__ == "__main__":
    unittest.main()
