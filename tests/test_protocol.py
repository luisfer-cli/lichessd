from __future__ import annotations

import unittest

from lichessd.protocol import Request, encode_event, encode_message


class TestRequest(unittest.TestCase):
    def test_parse_valid(self) -> None:
        req = Request.from_json('{"id": 1, "cmd": "games"}')
        assert req is not None
        self.assertEqual(req.id, 1)
        self.assertEqual(req.cmd, "games")
        self.assertEqual(req.params, {})

    def test_parse_with_params(self) -> None:
        req = Request.from_json('{"id": 2, "cmd": "move", "game_id": "abc", "move": "e2e4"}')
        assert req is not None
        self.assertEqual(req.params, {"game_id": "abc", "move": "e2e4"})

    def test_parse_invalid_json(self) -> None:
        self.assertIsNone(Request.from_json("not json"))

    def test_parse_missing_cmd(self) -> None:
        self.assertIsNone(Request.from_json('{"id": 1}'))

    def test_parse_non_string_cmd(self) -> None:
        self.assertIsNone(Request.from_json('{"id": 1, "cmd": 123}'))

    def test_default_id(self) -> None:
        req = Request.from_json('{"cmd": "games"}')
        assert req is not None
        self.assertEqual(req.id, 0)

    def test_to_response(self) -> None:
        req = Request(id=7, cmd="games")
        self.assertEqual(
            req.to_response(True, data={"x": 1}),
            '{"type": "response", "id": 7, "ok": true, "data": {"x": 1}}',
        )
        self.assertEqual(
            req.to_response(False, error="boom"),
            '{"type": "response", "id": 7, "ok": false, "error": "boom"}',
        )


class TestEncoding(unittest.TestCase):
    def test_encode_event(self) -> None:
        self.assertEqual(
            encode_event("move", game_id="abc", last_move="e7e5"),
            '{"type": "move", "game_id": "abc", "last_move": "e7e5"}',
        )

    def test_encode_message(self) -> None:
        self.assertEqual(encode_message({"a": 1}), '{"a": 1}\n')


if __name__ == "__main__":
    unittest.main()
