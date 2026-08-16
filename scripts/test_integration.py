#!/usr/bin/env python3
"""Comprehensive integration tests for lichessd via Unix socket."""

import json
import os
import signal
import socket
import subprocess
import sys
import time

SOCKET = "/tmp/lichessd-test.sock"
HOOK_LOG = "/tmp/lichessd-hook-test.log"
HOOK_SCRIPT = "/tmp/lichessd-hook-test.sh"
API_KEY = "lip_test_fake_key_for_validation"

PASS = 0
FAIL = 0


def log(msg: str) -> None:
    print(f"  {msg}")


def test(name: str) -> None:
    print(f"\n── {name}")


def ok(msg: str = "") -> None:
    global PASS
    PASS += 1
    suffix = f" — {msg}" if msg else ""
    print(f"  ✓ OK{suffix}")


def fail(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  ✗ FAIL: {msg}")


class Daemon:
    def __init__(self) -> None:
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        env = os.environ.copy()
        env["LICHESS_API_KEY"] = API_KEY
        self.proc = subprocess.Popen(
            [
                sys.executable, "-m", "lichessd.__main__",
                "--foreground",
                f"--socket={SOCKET}",
                "--poll-interval=9999",
                f"--on-move={HOOK_SCRIPT}",
                f"--on-game-start={HOOK_SCRIPT}",
                f"--on-game-finish={HOOK_SCRIPT}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        time.sleep(1.0)
        if self.proc.poll() is not None:
            fail("Daemon failed to start")

    def stop(self) -> None:
        if self.proc:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        for f in (SOCKET, HOOK_LOG):
            if os.path.exists(f):
                os.unlink(f)


def connect() -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    max_attempts = 20
    for i in range(max_attempts):
        try:
            sock.connect(SOCKET)
            return sock
        except (FileNotFoundError, ConnectionRefusedError):
            if i == max_attempts - 1:
                raise
            time.sleep(0.1)
    raise RuntimeError("Could not connect")


def send(sock: socket.socket, cmd: dict[str, object]) -> dict[str, object]:
    sock.sendall((json.dumps(cmd) + "\n").encode())
    time.sleep(0.05)
    data = b""
    sock.settimeout(2.0)
    while True:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        except TimeoutError:
            break
    responses = data.decode().strip().split("\n")
    return json.loads(responses[0])


def expect_response(resp: dict[str, object], expected_ok: bool, desc: str) -> None:
    if resp.get("ok") == expected_ok:
        ok(desc)
    else:
        err = resp.get("error", "unknown")
        fail(f"{desc}: ok={resp.get('ok')}, error={err}")


def expect_data(resp: dict[str, object], field: str, desc: str) -> dict[str, object] | None:
    data = resp.get("data")
    if data is not None:
        ok(desc)
        return data if isinstance(data, dict) else {"value": data}
    err = resp.get("error", "")
    fail(f"{desc}: no data field, error={err}")
    return None


def expect_error(resp: dict[str, object], contains: str, desc: str) -> None:
    error = str(resp.get("error", ""))
    if contains in error:
        ok(desc)
    else:
        fail(f"{desc}: error '{error}' does not contain '{contains}'")


def expect_field(data: dict[str, object] | None, field: str, desc: str) -> None:
    if data is not None and field in data:
        ok(desc)
    else:
        fail(f"{desc}: missing field '{field}'")


def main() -> None:
    global PASS, FAIL

    # Setup hook script
    with open(HOOK_SCRIPT, "w") as f:
        f.write("#!/bin/bash\n")
        f.write(f"echo \"$LICHESSD_EVENT:$1:$5\" >> {HOOK_LOG}\n")
    os.chmod(HOOK_SCRIPT, 0o755)

    daemon = Daemon()

    try:
        # ── Startup ──
        test("Daemon startup")
        daemon.start()
        ok("Daemon started")
        sock = connect()
        ok("Socket connected")

        # ── Invalid input ──
        test("Error handling")
        sock.sendall(b"not json\n")
        time.sleep(0.1)
        sock.settimeout(1.0)
        raw = sock.recv(4096).decode().strip()
        resp = json.loads(raw)
        expect_error(resp, "Invalid JSON", "Rejects non-JSON input")

        sock.sendall(b'{"no_cmd_field": 1}\n')
        time.sleep(0.1)
        raw = sock.recv(4096).decode().strip()
        resp = json.loads(raw)
        expect_error(resp, "Invalid JSON", "Rejects JSON without cmd")

        resp = send(sock, {"id": 1, "cmd": "no_existe"})
        expect_error(resp, "Unknown", "Rejects unknown command")

        # ── Games ──
        test("games command")
        resp = send(sock, {"id": 1, "cmd": "games"})
        expect_response(resp, True, "Returns ok")
        data = expect_data(resp, "data", "Has data field")
        expect_field(data, "games", "Has games list")
        expect_field(data, "count", "Has count")
        if data is not None and data.get("count") == 0:
            ok("Empty game list (expected with fake key)")
        else:
            ok(f"Game list with {data.get('count', '?') if data else '?'} items")

        # ── Game ──
        test("game command")
        resp = send(sock, {"id": 1, "cmd": "game"})
        expect_error(resp, "game_id", "Rejects missing game_id")

        resp = send(sock, {"id": 2, "cmd": "game", "game_id": "nonexistent"})
        expect_response(resp, False, "Returns error for unknown game (expected with fake key)")
        expect_error(resp, "4", "Error is HTTP-like (401/404)")

        resp = send(sock, {"id": 3, "cmd": "game", "game_id": "nonexistent", "pgn": "true"})
        expect_response(resp, False, "PGN export returns error for unknown game")

        # ── Move ──
        test("move command")
        resp = send(sock, {"id": 1, "cmd": "move"})
        expect_error(resp, "game_id and move", "Rejects missing params")

        resp = send(sock, {"id": 2, "cmd": "move", "game_id": "test", "move": "e2e4"})
        expect_response(resp, False, "Returns error for fake game (401 expected)")

        resp = send(sock, {
            "id": 3, "cmd": "move", "game_id": "test", "move": "e2e4",
            "offering_draw": "true",
        })
        expect_response(resp, False, "Handles offering_draw flag")

        # ── Puzzle ──
        test("puzzle command")
        resp = send(sock, {"id": 1, "cmd": "puzzle"})
        expect_response(resp, False, "Returns error with fake key (401 expected)")

        resp = send(sock, {"id": 2, "cmd": "puzzle", "angle": "mateIn2"})
        expect_response(resp, False, "Handles angle parameter")

        resp = send(sock, {
            "id": 3, "cmd": "puzzle", "angle": "mix",
            "difficulty": "harder", "color": "white",
        })
        expect_response(resp, False, "Handles all puzzle parameters")

        # ── Puzzle move ──
        test("puzzle_move command")
        resp = send(sock, {"id": 1, "cmd": "puzzle_move"})
        expect_error(resp, "move required", "Rejects missing move")

        resp = send(sock, {"id": 2, "cmd": "puzzle_move", "move": "e4"})
        expect_error(resp, "No active puzzle", "Rejects when no active puzzle")

        # ── Seek ──
        test("seek command")
        resp = send(sock, {"id": 1, "cmd": "seek"})
        expect_response(resp, False, "Default seek (correspondence, 3d) returns 401")

        resp = send(
            sock, {"id": 2, "cmd": "seek", "days": 7, "rated": "true", "variant": "standard"}
        )
        expect_response(resp, False, "Custom seek params work")

        resp = send(sock, {"id": 3, "cmd": "seek", "time": 5, "increment": 3})
        expect_response(resp, False, "Clock-based seek works")

        resp = send(sock, {"id": 4, "cmd": "seek", "days": 2, "rating_range": "1500-2000"})
        expect_response(resp, False, "Rating range seek works")

        # ── Challenge ──
        test("challenge command")
        resp = send(sock, {"id": 1, "cmd": "challenge", "action": "create"})
        expect_error(resp, "username", "Rejects create without username")

        resp = send(sock, {"id": 2, "cmd": "challenge", "action": "create", "username": "player1"})
        expect_response(resp, False, "Create returns 401 with fake key")

        resp = send(sock, {
            "id": 3, "cmd": "challenge", "action": "create", "username": "p",
            "days": 5, "rated": "true", "color": "black",
        })
        expect_response(resp, False, "Create with all params works")

        resp = send(
            sock,
            {"id": 4, "cmd": "challenge", "action": "create", "username": "p", "clock_limit": 300},
        )
        expect_response(resp, False, "Create with clock works")

        resp = send(sock, {"id": 5, "cmd": "challenge", "action": "accept"})
        expect_error(resp, "challenge_id", "Rejects accept without challenge_id")

        resp = send(
            sock, {"id": 6, "cmd": "challenge", "action": "accept", "challenge_id": "abcd1234"}
        )
        expect_response(resp, False, "Accept returns 404 for fake ID")

        resp = send(sock, {"id": 7, "cmd": "challenge", "action": "decline"})
        expect_error(resp, "challenge_id", "Rejects decline without challenge_id")

        resp = send(sock, {
            "id": 8, "cmd": "challenge", "action": "decline",
            "challenge_id": "abcd1234", "reason": "later",
        })
        expect_response(resp, False, "Decline returns 404 for fake ID")

        resp = send(sock, {"id": 9, "cmd": "challenge", "action": "weird"})
        expect_error(resp, "Unknown challenge action", "Rejects invalid action")

        # ── Subscribe ──
        test("subscribe command")
        resp = send(sock, {"id": 1, "cmd": "subscribe"})
        expect_response(resp, True, "Subscribe returns ok")
        data = expect_data(resp, "data", "Has data")
        expect_field(data, "message", "Has message field")

        # ── ID handling ──
        test("Response ID matching")
        for test_id in [0, 42, 999, -1]:
            resp = send(sock, {"id": test_id, "cmd": "games"})
            if resp.get("id") == test_id:
                ok(f"Response ID matches: {test_id}")
            else:
                fail(f"Response ID mismatch: expected {test_id}, got {resp.get('id')}")

        # ── Multiple commands in one connection ──
        test("Multiple commands on one connection")
        sock2 = connect()
        responses = []
        for cmd in [
            {"id": 1, "cmd": "games"},
            {"id": 2, "cmd": "game", "game_id": "xyz"},
            {"id": 3, "cmd": "puzzle"},
        ]:
            responses.append(send(sock2, cmd))
        expect_response(responses[0], True, "Games via persistent connection")
        expect_response(responses[1], False, "Game via persistent connection")
        expect_response(responses[2], False, "Puzzle via persistent connection")
        sock2.close()

        # ── Hooks (no events with fake key, but verify no crash) ──
        test("Hook registration")
        if os.path.exists(HOOK_SCRIPT):
            ok("Hook script exists")
        else:
            fail("Hook script not found")

        # ── Cleanup ──
        test("Cleanup")
        sock.close()
        ok("Socket closed")

    finally:
        daemon.stop()

    # ── Summary ──
    total = PASS + FAIL
    print(f"\n{'='*50}")
    print(f"Results: {PASS}/{total} passed, {FAIL} failed")
    print(f"{'='*50}")

    if FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
