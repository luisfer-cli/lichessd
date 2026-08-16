from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

import httpx

from lichessd.api import LichessAPI


def _api(handler: Any) -> LichessAPI:
    api = LichessAPI("key")
    api._client = httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(handler),
        base_url="https://lichess.org",
    )
    return api


class TestApiRequests(unittest.IsolatedAsyncioTestCase):
    async def test_get_playing(self) -> None:
        captured: dict[str, Any] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"nowPlaying": []})

        api = _api(handler)
        result = await api.get_playing(nb=10)
        self.assertEqual(captured["path"], "/api/account/playing")
        self.assertEqual(captured["params"], {"nb": "10"})
        self.assertEqual(result, {"nowPlaying": []})
        await api.close()

    async def test_make_move_with_draw(self) -> None:
        captured: dict[str, Any] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"ok": True})

        api = _api(handler)
        await api.make_move("g1", "e2e4", offering_draw=True)
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/api/board/game/g1/move/e2e4")
        self.assertEqual(captured["params"], {"offeringDraw": "true"})
        await api.close()

    async def test_make_move_without_draw(self) -> None:
        captured: dict[str, Any] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"ok": True})

        api = _api(handler)
        await api.make_move("g1", "e2e4")
        self.assertEqual(captured["params"], {})
        await api.close()

    async def test_get_puzzle_params(self) -> None:
        captured: dict[str, Any] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"puzzle": {"id": "p1"}})

        api = _api(handler)
        await api.get_puzzle(angle="mateIn2", difficulty="harder", color="white")
        self.assertEqual(
            captured["params"],
            {"angle": "mateIn2", "difficulty": "harder", "color": "white"},
        )
        await api.close()

    async def test_create_seek_correspondence(self) -> None:
        captured: dict[str, Any] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["content"] = request.content.decode()
            return httpx.Response(200, json={"ok": True})

        api = _api(handler)
        await api.create_seek(days=3, rated=True, variant="standard")
        self.assertIn("days=3", captured["content"])
        self.assertIn("rated=true", captured["content"])
        self.assertNotIn("time=", captured["content"])
        await api.close()

    async def test_create_seek_clock(self) -> None:
        captured: dict[str, Any] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["content"] = request.content.decode()
            return httpx.Response(200, json={"ok": True})

        api = _api(handler)
        await api.create_seek(time=5, increment=3)
        self.assertIn("time=5", captured["content"])
        self.assertIn("increment=3", captured["content"])
        self.assertNotIn("days=", captured["content"])
        await api.close()

    async def test_create_challenge(self) -> None:
        captured: dict[str, Any] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["content"] = request.content.decode()
            return httpx.Response(200, json={"ok": True})

        api = _api(handler)
        await api.create_challenge("juan", days=2, rated=True, color="black")
        self.assertEqual(captured["path"], "/api/challenge/juan")
        self.assertIn("days=2", captured["content"])
        self.assertIn("color=black", captured["content"])
        await api.close()

    async def test_export_game_json(self) -> None:
        captured: dict[str, Any] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["accept"] = request.headers.get("accept")
            return httpx.Response(200, json={"id": "g1"})

        api = _api(handler)
        result = await api.export_game("g1", as_pgn=False)
        self.assertEqual(captured["accept"], "application/json")
        self.assertEqual(result, {"id": "g1"})
        await api.close()

    async def test_retry_on_429(self) -> None:
        attempts = {"n": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] < 3:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json={"ok": True})

        api = _api(handler)
        with mock.patch("lichessd.api.RETRY_DELAY", 0.0):
            result = await api.get_playing()
        self.assertEqual(attempts["n"], 3)
        self.assertEqual(result, {"ok": True})
        await api.close()


if __name__ == "__main__":
    unittest.main()
