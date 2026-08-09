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
            timeout=httpx.Timeout(30.0),
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
        return await self._client.send(
            self._client.build_request("GET", "/api/stream/event"),
            stream=True,
        )

    async def stream_game(self, game_id: str) -> httpx.Response:
        return await self._client.send(
            self._client.build_request("GET", f"/api/board/game/stream/{game_id}"),
            stream=True,
        )

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
