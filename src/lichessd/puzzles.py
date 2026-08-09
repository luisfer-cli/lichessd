from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lichessd.api import LichessAPI


async def fetch_puzzle(
    api: LichessAPI,
    angle: str = "mix",
    difficulty: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    return await api.get_puzzle(angle=angle, difficulty=difficulty, color=color)
