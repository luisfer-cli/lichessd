# lichessd

Unix daemon for [Lichess](https://lichess.org) correspondence chess — play, watch, and get notified
about your games entirely from the terminal.

## Features

- Connects to Lichess via personal API token
- Detects new moves in correspondence games via polling + real-time event streaming
- Sends moves and draw offers to specific games
- Seeks new correspondence games and handles challenges
- Fetches random puzzles by theme, difficulty, and color
- Communicates through a local **Unix socket** using newline-delimited JSON
- Fires external **hook commands** (`--on-move`, `--on-game-start`, `--on-game-finish`) when game events occur
- Classic Unix daemon: double-fork, PID file, signal handling

## Quick start

```bash
# Install
git clone https://github.com/luisfer-cli/lichessd
cd lichessd && uv sync

# Get your API token at https://lichess.org/account/oauth/token
# (enable scopes: board:play, puzzle:read, challenge:write)
mkdir -p ~/.lichessd
echo "api_key=lip_your_token_here" > ~/.lichessd/config

# Run
uv run lichessd

# Communicate via the Unix socket
echo '{"id":1,"cmd":"games"}' | socat - UNIX-CONNECT:~/.lichessd/socket
echo '{"id":1,"cmd":"puzzle"}' | socat - UNIX-CONNECT:~/.lichessd/socket
```

## Installation

### From source

```bash
uv sync
```

### Build a standalone binary

```bash
./scripts/build.sh
# Binary at dist/lichessd
```

### Requirements
- Python ≥ 3.10
- [uv](https://github.com/astral-sh/uv) (or pip with `httpx`)

## Configuration

The API key is resolved in this order (first match wins):

1. `--api-key` CLI argument
2. `LICHESS_API_KEY` environment variable
3. `~/.lichessd/config` file

### Config file format

```
# ~/.lichessd/config
api_key=lip_your_token_here
```

Or just the token on the first line:

```
lip_your_token_here
```

## CLI reference

```
lichessd [OPTIONS]

Options:
  --api-key KEY          Lichess API token
  --config PATH          Config file path (default: ~/.lichessd/config)
  --socket PATH          Unix socket path (default: ~/.lichessd/socket)
  --pid-file PATH        PID file path (default: ~/.lichessd/lichessd.pid)
  --on-move COMMAND      Hook: run COMMAND when a new move arrives
  --on-game-start COMMAND Hook: run COMMAND when a correspondence game starts
  --on-game-finish COMMAND Hook: run COMMAND when a correspondence game ends
  --poll-interval SECS   Seconds between API polls (default: 30)
  --default-angle THEME  Default puzzle theme (default: mix)
  --daemonize, -d        Detach and run in the background
  --foreground, -f       Stay in foreground (default behavior)
```

### Examples

```bash
# Run in foreground with hook scripts
lichessd --on-move ~/bin/notify-move.sh --on-game-start ~/bin/notify-game.sh

# Daemonize
lichessd -d

# Custom socket and poll interval
lichessd --socket /tmp/chess.sock --poll-interval 60
```

## Unix socket protocol

The daemon listens on a Unix domain socket. Communication uses **newline-delimited JSON**
(one JSON object per line, terminated by `\n`).

### Request format

```json
{"id": 1, "cmd": "<command>", "param1": "value1", ...}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | int | Yes | Request identifier, echoed in the response |
| `cmd` | string | Yes | Command name |
| (all others) | any | — | Command-specific parameters |

### Response format

```json
{"type": "response", "id": 1, "ok": true, "data": {...}}
```

```json
{"type": "response", "id": 1, "ok": false, "error": "description"}
```

### Event format (streaming)

When you send a `subscribe` command, the daemon pushes events as they happen:

```json
{"type": "move", "game_id": "abc123", "fen": "rnbq...", "last_move": "e7e5", ...}
{"type": "game_start", "game_id": "def456", "opponent": {"username": "juanito"}, ...}
{"type": "game_finish", "game_id": "ghi789"}
```

## Commands

### `games` — List active games

```bash
echo '{"id":1,"cmd":"games"}' | socat - UNIX-CONNECT:~/.lichessd/socket
```

Response:

```json
{
  "type": "response",
  "id": 1,
  "ok": true,
  "data": {
    "games": [
      {
        "game_id": "abc123",
        "full_id": "abc123xxxx",
        "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -",
        "last_move": "e7e5",
        "is_my_turn": true,
        "color": "white",
        "opponent": { "id": "juanito", "username": "Juanito", "rating": 1500 },
        "rated": true,
        "seconds_left": 1209600
      }
    ],
    "count": 1
  }
}
```

### `game` — Get a single game's board state

```bash
# JSON game state
echo '{"id":1,"cmd":"game","game_id":"abc123"}' | socat - UNIX-CONNECT:~/.lichessd/socket

# With PGN export
echo '{"id":1,"cmd":"game","game_id":"abc123","pgn":"true"}' | socat - UNIX-CONNECT:~/.lichessd/socket
```

### `move` — Send a move

```bash
# Send a move in UCI format
echo '{"id":1,"cmd":"move","game_id":"abc123","move":"e2e4"}' | socat - UNIX-CONNECT:~/.lichessd/socket

# Offer/accept a draw
echo '{"id":1,"cmd":"move","game_id":"abc123","move":"e2e4","offering_draw":"true"}' | socat - UNIX-CONNECT:~/.lichessd/socket
```

### `puzzle` — Get a random puzzle

```bash
# Random puzzle, default theme
echo '{"id":1,"cmd":"puzzle"}' | socat - UNIX-CONNECT:~/.lichessd/socket

# Specific theme, difficulty, and color
echo '{"id":2,"cmd":"puzzle","angle":"mateIn2","difficulty":"harder","color":"white"}' | socat - UNIX-CONNECT:~/.lichessd/socket
```

Response includes `puzzle.id`, `puzzle.fen`, `puzzle.rating`, `puzzle.solution` (UCI moves),
`puzzle.themes`, and the source game with player info.

### `seek` — Look for a correspondence game

```bash
# Default: correspondence, 3 days per move, random color
echo '{"id":1,"cmd":"seek"}' | socat - UNIX-CONNECT:~/.lichessd/socket

# Correspondence, 7 days, rated
echo '{"id":1,"cmd":"seek","days":7,"rated":"true","color":"white"}' | socat - UNIX-CONNECT:~/.lichessd/socket

# Rated with rating range
echo '{"id":1,"cmd":"seek","days":2,"rating_range":"1500-2000"}' | socat - UNIX-CONNECT:~/.lichessd/socket

# Real-time clock (blitz/rapid)
echo '{"id":1,"cmd":"seek","time":5,"increment":3,"rated":"true"}' | socat - UNIX-CONNECT:~/.lichessd/socket
```

Parameters: `days`, `time`, `increment`, `rated`, `variant`, `rating_range`, `color`.

Defaults to correspondence (`days=3`) and random color when neither `days` nor `time` is specified.

### `challenge` — Create, accept, or decline a challenge

```bash
# Create a challenge to a specific user (correspondence by default)
echo '{"id":1,"cmd":"challenge","action":"create","username":"juanito","days":2}' | socat - UNIX-CONNECT:~/.lichessd/socket

# Create with custom starting position
echo '{"id":1,"cmd":"challenge","action":"create","username":"juanito","fen":"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"}' | socat - UNIX-CONNECT:~/.lichessd/socket

# Accept an incoming challenge
echo '{"id":1,"cmd":"challenge","action":"accept","challenge_id":"abcd1234"}' | socat - UNIX-CONNECT:~/.lichessd/socket

# Decline with reason
echo '{"id":1,"cmd":"challenge","action":"decline","challenge_id":"abcd1234","reason":"later"}' | socat - UNIX-CONNECT:~/.lichessd/socket
```

### `subscribe` — Receive streaming events

```bash
# Connect and subscribe. Keep the connection open to receive events.
echo '{"cmd":"subscribe"}' | socat - UNIX-CONNECT:~/.lichessd/socket
```

After subscribing, the daemon will push events as they arrive:

```json
{"type":"game_start","game_id":"abc123","fen":"...","opponent":{"username":"juanito"},...}
{"type":"move","game_id":"abc123","last_move":"e7e5","is_my_turn":true,...}
{"type":"game_finish","game_id":"abc123"}
```

## Hooks — external script execution

Hooks execute a shell command when a game event occurs. Data is passed as **positional
arguments** and **environment variables**.

### Command-line arguments (in order)

```
command 'game_id' 'move' 'fen' 'color' 'is_my_turn'
```

### Environment variables

| Variable | Value |
|----------|-------|
| `LICHESSD_EVENT` | `move`, `game_start`, or `game_finish` |
| `LICHESSD_GAME_ID` | Game ID (e.g. `abc123`) |
| `LICHESSD_FULL_ID` | Full ID with player suffix |
| `LICHESSD_FEN` | Current board position |
| `LICHESSD_LAST_MOVE` | Last move in UCI format |
| `LICHESSD_IS_MY_TURN` | `True` or `False` |
| `LICHESSD_COLOR` | `white` or `black` |
| `LICHESSD_OPPONENT_USERNAME` | Opponent's Lichess username |
| `LICHESSD_OPPONENT_ID` | Opponent's Lichess user ID |
| `LICHESSD_SECONDS_LEFT` | Remaining clock in seconds |

### Example hook script

```bash
#!/bin/bash
# ~/bin/chess-notify.sh — desktop notification on new games or moves
case "$LICHESSD_EVENT" in
    game_start)
        notify-send "Chess" "New game vs $LICHESSD_OPPONENT_USERNAME" --icon=chess
        ;;
    move)
        if [ "$LICHESSD_IS_MY_TURN" = "True" ]; then
            notify-send "Your turn!" "Game $LICHESSD_GAME_ID — $LICHESSD_LAST_MOVE" --icon=chess
        fi
        ;;
    game_finish)
        notify-send "Chess" "Game $LICHESSD_GAME_ID finished" --icon=chess
        ;;
esac
```

```bash
lichessd --on-move ~/bin/chess-notify.sh \
         --on-game-start ~/bin/chess-notify.sh \
         --on-game-finish ~/bin/chess-notify.sh
```

## How it works

```
┌────────────┐   ┌──────────────┐   ┌─────────────────┐
│  nc/socat  │──▶│ Unix socket  │──▶│  LichessAPI      │──▶ lichess.org
│  scripts   │   │ (JSON lines) │   │  (httpx client)  │
│  apps      │◀──│              │◀──│                  │◀──
└────────────┘   └──────────────┘   └─────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │    GameStore    │
              │  (poll + SSE)   │
              └─────────────────┘
```

1. **Polling** (`GET /api/account/playing` every 30s): detects changes in existing
   correspondence games by comparing FEN and last move.
2. **Event streaming** (`GET /api/stream/event`): real-time SSE connection for new game
   starts, challenges, and game completions.
3. **Unix socket server**: accepts client connections, dispatches commands, broadcasts
   events to all connected clients.
4. **Hooks**: external shell scripts run asynchronously on game events.

## Building a standalone binary

```bash
./scripts/build.sh
# Output: dist/lichessd (ELF 64-bit, ~12 MB)
```

The script uses PyInstaller to bundle Python + httpx into a single binary. Requires the
project venv with PyInstaller installed (`uv add --dev pyinstaller`).

## Testing

```bash
uv run python scripts/test_integration.py
```

The test suite starts the daemon with a fake API key, connects to the socket, and verifies
all 7 commands, error handling, ID matching, persistent connections, and hook registration.

## API key

Get your token at [https://lichess.org/account/oauth/token](https://lichess.org/account/oauth/token).

Required scopes:
- `board:play` — play games, stream events, create seeks
- `puzzle:read` — fetch puzzles
- `challenge:write` — accept/decline challenges

## Architecture

```
src/lichessd/
├── __init__.py       Package metadata (version 0.1.0)
├── __main__.py       Entry point, CLI parsing, asyncio orchestration
├── api.py            LichessAPI — all HTTP calls, retry logic, rate limiting
├── config.py         Config — CLI args, env vars, config file parsing
├── daemon.py         Daemonization (double-fork), PID file, signal handlers
├── games.py          GameStore — polling, SSE event streaming, game state tracking
├── notify.py         Hook command execution with environment variables
├── protocol.py       JSON Lines encoding/decoding for Unix socket protocol
├── puzzles.py        Puzzle fetching helper
└── server.py         UnixSocketServer — socket listener, command dispatch, event broadcast
```

## License

MIT
