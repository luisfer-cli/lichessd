from __future__ import annotations

import asyncio
import logging

from lichessd.api import LichessAPI
from lichessd.config import Config
from lichessd.daemon import daemonize, install_signal_handlers, should_shutdown
from lichessd.games import GameStore
from lichessd.server import UnixSocketServer

logger = logging.getLogger(__name__)


def main() -> None:
    config = Config.from_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    config.socket_path.parent.mkdir(parents=True, exist_ok=True)

    if config.pid_file:
        config.pid_file.parent.mkdir(parents=True, exist_ok=True)

    if config.daemonize and not config.foreground:
        daemonize(config.pid_file)
    else:
        install_signal_handlers()

    try:
        asyncio.run(_run(config))
    except KeyboardInterrupt:
        pass
    finally:
        if config.pid_file and config.pid_file.exists():
            config.pid_file.unlink()


async def _run(config: Config) -> None:
    api = LichessAPI(config.api_key)
    store = GameStore(api=api)
    server = UnixSocketServer(
        socket_path=str(config.socket_path),
        game_store=store,
        on_move_command=config.on_move,
        on_game_start_command=config.on_game_start,
        on_game_finish_command=config.on_game_finish,
        default_angle=config.default_angle,
    )

    async def _shutdown_watch() -> None:
        while not should_shutdown():
            await asyncio.sleep(1)

    try:
        await server.start()
        await store.start(poll_interval=config.poll_interval)

        watch_task = asyncio.create_task(_shutdown_watch())

        _done, pending = await asyncio.wait(
            [watch_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        logger.info("Shutting down...")
        await store.stop()
        await server.stop()
        await api.close()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
