from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Request:
    id: int
    cmd: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: str) -> Request | None:
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            return None
        req_id = obj.get("id", 0)
        cmd = obj.get("cmd", "")
        params = {k: v for k, v in obj.items() if k not in ("id", "cmd")}
        if not cmd or not isinstance(cmd, str):
            return None
        return cls(id=int(req_id), cmd=cmd, params=params)

    def to_response(self, ok: bool, data: Any = None, error: str | None = None) -> str:
        resp: dict[str, Any] = {"type": "response", "id": self.id, "ok": ok}
        if data is not None:
            resp["data"] = data
        if error is not None:
            resp["error"] = error
        return json.dumps(resp)


def encode_event(event_type: str, **kwargs: Any) -> str:
    return json.dumps({"type": event_type, **kwargs})


def encode_message(obj: dict[str, Any]) -> str:
    return json.dumps(obj) + "\n"
