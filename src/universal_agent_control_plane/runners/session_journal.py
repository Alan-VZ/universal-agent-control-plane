from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..storage import StateStore

_MIN_SUMMARY_LENGTH = 200


def _store() -> StateStore:
    project_root = Path(__file__).resolve().parents[3]
    return StateStore(Path(os.environ.get("UACP_DATA_DIR", project_root / ".data")))


def load_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Return recent session summaries as context for a starting session.

    Both hosts accept `additionalContext` on session start, so one handler
    gives every agent the same recall.
    """
    entries = _store().recent_journal(limit=3)
    if not entries:
        return {"additionalContext": "", "entries": 0}
    lines = [
        f"- {entry['createdAt']}: {entry['summary'].splitlines()[0][:200]}"
        for entry in entries
    ]
    context = "## Recent session history\n" + "\n".join(lines)
    return {"additionalContext": context, "entries": len(entries)}


def record_session(payload: dict[str, Any]) -> dict[str, Any]:
    """Journal a finished session, enforcing the anti-bloat policy.

    The summary must be supplied by the caller. This handler never invokes a
    model, so a session ending can never spawn another billable agent run.
    """
    session_id = payload.get("sessionId")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("payload.sessionId is required")
    if payload.get("isSubagent"):
        return {"stored": False, "reason": "sub-agent"}

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        # Nothing to store yet: the host fired the event without a summary.
        # Report the gap instead of writing an empty journal entry.
        return {"stored": False, "reason": "no-summary-provided"}

    tags = payload.get("tags")
    result = _store().append_journal(
        session_id=session_id.strip(),
        summary=summary,
        tags=tags if isinstance(tags, list) else [],
        minimum_length=_MIN_SUMMARY_LENGTH,
    )
    return result
