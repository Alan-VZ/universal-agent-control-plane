from __future__ import annotations

import json
from pathlib import Path

import pytest

from universal_agent_control_plane.execution import SkillExecutor
from universal_agent_control_plane.hooks import (
    HookDispatcher,
    HookError,
    canonical_event,
    normalize,
)
from universal_agent_control_plane.registry import Registry
from universal_agent_control_plane.storage import StateStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def dispatcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HookDispatcher:
    monkeypatch.setenv("UACP_DATA_DIR", str(tmp_path))
    registry = Registry(PROJECT_ROOT / "registry")
    executor = SkillExecutor(registry, StateStore(tmp_path))
    return HookDispatcher(registry, executor, StateStore(tmp_path))


def test_canonical_event_accepts_every_host_spelling() -> None:
    assert canonical_event("sessionEnd") == "session_end"
    assert canonical_event("SessionEnd") == "session_end"
    assert canonical_event("session_end") == "session_end"
    assert canonical_event("UserPromptSubmit") == "user_prompt"
    assert canonical_event("userPromptSubmitted") == "user_prompt"


def test_canonical_event_rejects_unknown_events() -> None:
    with pytest.raises(HookError):
        canonical_event("somethingElse")


def test_normalize_reads_copilot_camel_case_payload() -> None:
    event = normalize(
        "sessionEnd",
        {"sessionId": "abc", "timestamp": 1_700_000_000_000, "reason": "complete"},
    )
    assert event.event == "session_end"
    assert event.session_id == "abc"
    assert event.reason == "complete"
    assert event.timestamp.endswith("Z")


def test_normalize_reads_claude_snake_case_payload() -> None:
    event = normalize(
        "SessionEnd",
        {
            "hook_event_name": "SessionEnd",
            "session_id": "xyz",
            "timestamp": "2026-01-01T00:00:00Z",
            "reason": "user_exit",
        },
    )
    assert event.event == "session_end"
    assert event.session_id == "xyz"
    assert event.source_event == "SessionEnd"


def test_normalize_rejects_mismatched_declared_event() -> None:
    with pytest.raises(HookError):
        normalize("sessionStart", {"hook_event_name": "SessionEnd"})


def test_subagent_session_end_is_skipped(dispatcher: HookDispatcher) -> None:
    response = dispatcher.dispatch(
        "SessionEnd",
        {"session_id": "s1", "agent_type": "summarizer", "summary": "x" * 400},
    )
    assert response["handled"] is False
    assert response["skipped"] == "sub-agent"
    assert dispatcher.state.recent_journal() == []


def test_session_end_records_journal_entry(dispatcher: HookDispatcher) -> None:
    payload = {"session_id": "s2", "summary": "y" * 400}
    response = dispatcher.dispatch("SessionEnd", payload)
    assert response["handled"] is True
    entries = dispatcher.state.recent_journal()
    assert len(entries) == 1
    assert entries[0]["sessionId"] == "s2"


def test_repeat_delivery_is_ignored(dispatcher: HookDispatcher) -> None:
    payload = {"session_id": "s3", "summary": "z" * 400}
    assert dispatcher.dispatch("SessionEnd", payload)["handled"] is True
    repeat = dispatcher.dispatch("SessionEnd", payload)
    assert repeat["handled"] is False
    assert repeat["skipped"] == "duplicate-event"
    assert len(dispatcher.state.recent_journal()) == 1


def test_short_summary_is_rejected_as_bloat(dispatcher: HookDispatcher) -> None:
    dispatcher.dispatch("SessionEnd", {"session_id": "s4", "summary": "too short"})
    assert dispatcher.state.recent_journal() == []


def test_session_start_returns_context_for_both_hosts(
    dispatcher: HookDispatcher,
) -> None:
    dispatcher.dispatch("SessionEnd", {"session_id": "s5", "summary": "a" * 400})
    response = dispatcher.dispatch("SessionStart", {"session_id": "s6"})
    assert response["handled"] is True
    assert "Recent session history" in response["additionalContext"]
    assert response["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_missing_session_id_is_rejected(dispatcher: HookDispatcher) -> None:
    with pytest.raises(HookError):
        dispatcher.dispatch("SessionEnd", {"summary": "b" * 400})


def test_handler_failure_does_not_break_the_session(
    dispatcher: HookDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    from universal_agent_control_plane.runners import session_journal

    def explode(_: dict[str, object]) -> dict[str, object]:
        raise ValueError("handler exploded")

    monkeypatch.setattr(session_journal, "record_session", explode)
    response = dispatcher.dispatch("SessionEnd", {"session_id": "s7", "summary": "b" * 400})
    assert response["handled"] is True
    assert response["results"][0]["status"] == "error"


def test_events_lists_configured_handlers(dispatcher: HookDispatcher) -> None:
    events = dispatcher.events()
    names = {item["event"] for item in events["events"]}
    assert {"session_start", "session_end"} <= names
    assert "session_end" in events["rootSessionsOnly"]


def test_non_allow_listed_handler_is_refused(dispatcher: HookDispatcher) -> None:
    with pytest.raises(Exception):
        dispatcher.executor.run_reference(
            "universal_agent_control_plane.runners.greeting:run", {}
        )


def test_cli_hook_reports_errors_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess
    import sys

    environment = {
        "PATH": "",
        "SYSTEMROOT": "C:\\Windows",
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        "UACP_DATA_DIR": str(tmp_path),
        "UACP_REGISTRY_ROOT": str(PROJECT_ROOT / "registry"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "universal_agent_control_plane.cli", "hook", "sessionEnd"],
        input=json.dumps({"sessionId": "cli1", "summary": "c" * 400}),
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["handled"] is True
