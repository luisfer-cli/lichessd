from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_ENV_KEYS = (
    "game_id",
    "full_id",
    "fen",
    "last_move",
    "is_my_turn",
    "color",
    "opponent",
    "seconds_left",
)
_ARGS_KEYS = ("game_id", "last_move", "fen", "color", "is_my_turn")


async def run_hook(command: str, event_type: str, event_data: dict[str, Any]) -> None:
    if not command:
        return

    rendered = _render_command(command, event_data)
    env = _build_env(event_type, event_data)

    try:
        proc = await asyncio.create_subprocess_shell(
            rendered,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        if proc.returncode != 0:
            logger.warning(
                "Hook command exited with %d: %s\nstderr: %s",
                proc.returncode,
                rendered,
                stderr.decode(errors="replace"),
            )
        elif stdout:
            logger.info("Hook stdout: %s", stdout.decode(errors="replace").strip())
    except TimeoutError:
        logger.warning("Hook command timed out after 30s: %s", rendered)
    except Exception:
        logger.exception("Hook command failed: %s", rendered)


def _render_command(command: str, data: dict[str, Any]) -> str:
    args = " ".join(sh_quote(str(data.get(k, ""))) for k in _ARGS_KEYS)
    return f"{command} {args}"


def _build_env(event_type: str, data: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    env["LICHESSD_EVENT"] = event_type
    for k in _ENV_KEYS:
        val = data.get(k, "")
        env[f"LICHESSD_{k.upper()}"] = str(val)
    opponent = data.get("opponent", {})
    if isinstance(opponent, dict):
        env["LICHESSD_OPPONENT_USERNAME"] = str(opponent.get("username", ""))
        env["LICHESSD_OPPONENT_ID"] = str(opponent.get("id", ""))
    return env


def sh_quote(s: str) -> str:
    if not s:
        return "''"
    if "'" not in s:
        return f"'{s}'"
    return "'" + s.replace("'", "'\\''") + "'"
