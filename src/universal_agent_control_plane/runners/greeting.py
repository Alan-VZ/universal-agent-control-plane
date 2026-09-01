from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any]) -> dict[str, str]:
    name = payload.get("name", "agent")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError("payload.name must be a non-empty string of at most 100 characters")
    return {"result": f"Hello {name}, the shared skill is active."}
