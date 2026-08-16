from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)

LICHESS_BASE = "https://lichess.org"
MAX_RETRIES = 3
RETRY_DELAY = 5.0


class LichessAPI:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=LICHESS_BASE,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(10.0, connect=10.0, read=30.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        retries: int = MAX_RETRIES,
        **kwargs: Any,
    ) -> httpx.Response:
        last_resp: httpx.Response | None = None
        for attempt in range(retries):
            resp = await self._client.request(method, path, **kwargs)
            last_resp = resp
            if resp.status_code == 429:
                delay = RETRY_DELAY * (attempt + 1)
                logger.warning(
                    "Rate limited (429) on %s %s, retrying in %.1fs",
                    method,
                    path,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        msg = f"Failed after {retries} retries on {method} {path}"
        assert last_resp is not None
        raise httpx.HTTPStatusError(msg, request=last_resp.request, response=last_resp)

    async def get_playing(self, nb: int = 20) -> dict[str, Any]:
        resp = await self._request("GET", "/api/account/playing", params={"nb": nb})
        return cast("dict[str, Any]", resp.json())

    async def stream_events(self) -> httpx.Response:
        request = self._client.build_request("GET", "/api/stream/event")
        request.extensions = {"timeout": {"read": None}}
        return await self._client.send(request, stream=True)

    async def stream_game(self, game_id: str) -> httpx.Response:
        request = self._client.build_request(
            "GET",
            f"/api/board/game/stream/{game_id}",
        )
        request.extensions = {"timeout": {"read": None}}
        return await self._client.send(request, stream=True)

    async def make_move(
        self,
        game_id: str,
        move: str,
        *,
        offering_draw: bool = False,
    ) -> dict[str, Any]:
        params = {}
        if offering_draw:
            params["offeringDraw"] = "true"
        resp = await self._request(
            "POST",
            f"/api/board/game/{game_id}/move/{move}",
            params=params,
        )
        return cast("dict[str, Any]", resp.json())

    async def get_puzzle(
        self,
        angle: str = "mix",
        difficulty: str | None = None,
        color: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {"angle": angle}
        if difficulty:
            params["difficulty"] = difficulty
        if color:
            params["color"] = color
        resp = await self._request("GET", "/api/puzzle/next", params=params)
        return cast("dict[str, Any]", resp.json())

    async def get_daily_puzzle(self) -> dict[str, Any]:
        resp = await self._request("GET", "/api/puzzle/daily")
        return cast("dict[str, Any]", resp.json())

    async def export_game(
        self,
        game_id: str,
        *,
        as_pgn: bool = True,
        moves: bool = True,
        tags: bool = True,
        clocks: bool = True,
        evals: bool = True,
        opening: bool = True,
        literate: bool = False,
    ) -> dict[str, Any] | str:
        params: dict[str, str | int] = {
            "moves": str(moves).lower(),
            "tags": str(tags).lower(),
            "clocks": str(clocks).lower(),
            "evals": str(evals).lower(),
            "opening": str(opening).lower(),
            "literate": str(literate).lower(),
        }
        headers: dict[str, str] = {}
        if not as_pgn:
            headers["Accept"] = "application/json"
        resp = await self._request(
            "GET",
            f"/api/game/export/{game_id}",
            params=params,
            headers=headers,
        )
        if as_pgn:
            return resp.text
        return cast("dict[str, Any]", resp.json())

    async def create_seek(
        self,
        *,
        days: int | None = None,
        time: float | None = None,
        increment: int = 5,
        rated: bool = False,
        variant: str = "standard",
        rating_range: str | None = None,
        color: str = "random",
    ) -> dict[str, Any]:
        data: dict[str, str | int | float] = {
            "rated": str(rated).lower(),
            "variant": variant,
            "color": color,
        }
        if days is not None:
            data["days"] = days
        else:
            data["time"] = time if time is not None else 10
            data["increment"] = increment
        if rating_range:
            data["ratingRange"] = rating_range
        resp = await self._request(
            "POST",
            "/api/board/seek",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return cast("dict[str, Any]", resp.json())

    async def create_challenge(
        self,
        username: str,
        *,
        days: int | None = None,
        clock_limit: int | None = None,
        clock_increment: int = 5,
        rated: bool = False,
        variant: str = "standard",
        color: str = "random",
        fen: str | None = None,
        message: str | None = None,
        keep_alive_stream: bool = False,
    ) -> dict[str, Any]:
        data: dict[str, str | int] = {
            "rated": str(rated).lower(),
            "variant": variant,
            "color": color,
        }
        if days is not None:
            data["days"] = days
        elif clock_limit is not None:
            data["clock.limit"] = clock_limit
            data["clock.increment"] = clock_increment
        if fen:
            data["fen"] = fen
        if message:
            data["message"] = message
        if keep_alive_stream:
            data["keepAliveStream"] = "true"
        resp = await self._request(
            "POST",
            f"/api/challenge/{username}",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return cast("dict[str, Any]", resp.json())

    async def accept_challenge(self, challenge_id: str) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            f"/api/challenge/accept/{challenge_id}",
        )
        return cast("dict[str, Any]", resp.json())

    async def decline_challenge(
        self,
        challenge_id: str,
        *,
        reason: str = "generic",
    ) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            f"/api/challenge/decline/{challenge_id}",
            data={"reason": reason},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return cast("dict[str, Any]", resp.json())

    async def answer_puzzle(
        self,
        puzzle_id: str,
        solution: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {}
        if solution:
            params["solution"] = " ".join(solution)
        resp = await self._request(
            "POST",
            f"/api/puzzle/{puzzle_id}/answer",
            data=params or None,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return cast("dict[str, Any]", resp.json())
