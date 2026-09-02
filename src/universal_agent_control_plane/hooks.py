from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .execution import SkillExecutor
from .registry import Registry, RegistryError
from .storage import StateStore

logger = logging.getLogger(__name__)

CANONICAL_EVENTS = (
    "session_start",
    "session_end",
    "user_prompt",
    "pre_tool_use",
    "post_tool_use",
    "subagent_start",
    "subagent_stop",
    "agent_stop",
    "notification",
)

# Both hosts emit the same lifecycle points under different spellings.
# Copilot accepts camelCase and a VS Code compatible PascalCase form.
# Claude Code emits PascalCase. Everything below normalizes to one name.
EVENT_ALIASES: dict[str, str] = {
    "sessionstart": "session_start",
    "sessionend": "session_end",
    "userpromptsubmit": "user_prompt",
    "userpromptsubmitted": "user_prompt",
    "pretooluse": "pre_tool_use",
    "posttooluse": "post_tool_use",
    "subagentstart": "subagent_start",
    "subagentstop": "subagent_stop",
    "stop": "agent_stop",
    "agentstop": "agent_stop",
    "notification": "notification",
}

_SUBAGENT_EVENTS = frozenset({"subagent_start", "subagent_stop"})
_MAX_TEXT = 4_000


class HookError(ValueError):
    """Raised when a hook event cannot be accepted or dispatched."""


@dataclass(frozen=True)
class HookEvent:
    """One lifecycle event normalized across hosts."""

    event: str
    session_id: str
    timestamp: str
    source_event: str
    cwd: str | None = None
    reason: str | None = None
    source: str | None = None
    prompt: str | None = None
    tool_name: str | None = None
    agent_id: str | None = None
    agent_type: str | None = None
    summary: str | None = None
    tags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_subagent(self) -> bool:
        """Whether this event came from a sub-agent rather than a root session."""
        return (
            self.event in _SUBAGENT_EVENTS
            or self.agent_id is not None
            or self.agent_type is not None
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "sessionId": self.session_id,
            "timestamp": self.timestamp,
            "sourceEvent": self.source_event,
            "cwd": self.cwd,
            "reason": self.reason,
            "source": self.source,
            "prompt": self.prompt,
            "toolName": self.tool_name,
            "agentId": self.agent_id,
            "agentType": self.agent_type,
            "isSubagent": self.is_subagent,
            "summary": self.summary,
            "tags": list(self.tags),
        }


def canonical_event(name: str) -> str:
    """Map any supported host spelling of an event onto its canonical name."""
    if not isinstance(name, str) or not name.strip():
        raise HookError("Hook event name is required")
    key = name.strip().replace("_", "").replace("-", "").casefold()
    canonical = EVENT_ALIASES.get(key)
    if canonical is None:
        raise HookError(f"Unsupported hook event: {name}")
    return canonical


def normalize(event_name: str, payload: dict[str, Any]) -> HookEvent:
    """Normalize a host hook payload into a canonical event.

    Accepts the Copilot camelCase form, the VS Code compatible snake_case
    form, and the Claude Code form without requiring the caller to know
    which host produced the payload.
    """
    if not isinstance(payload, dict):
        raise HookError("Hook payload must be an object")

    declared = payload.get("hook_event_name") or payload.get("hookEventName")
    resolved = canonical_event(event_name)
    if isinstance(declared, str) and declared.strip():
        declared_event = canonical_event(declared)
        if declared_event != resolved:
            raise HookError(
                f"Payload event {declared} does not match requested event {event_name}"
            )

    session_identifier = _text(payload, "sessionId", "session_id")
    if session_identifier is None:
        raise HookError("Hook payload must include sessionId")

    return HookEvent(
        event=resolved,
        session_id=session_identifier,
        timestamp=_timestamp(payload),
        source_event=str(declared).strip() if isinstance(declared, str) else event_name,
        cwd=_text(payload, "cwd", "workingDirectory", "working_directory"),
        reason=_text(payload, "reason"),
        source=_text(payload, "source"),
        prompt=_text(payload, "prompt", "initialPrompt", "initial_prompt"),
        tool_name=_text(payload, "toolName", "tool_name"),
        agent_id=_text(payload, "agentId", "agent_id"),
        agent_type=_text(payload, "agentType", "agent_type"),
        summary=_summary(payload),
        tags=[
            tag.strip()[:64]
            for tag in payload.get("tags", [])
            if isinstance(tag, str) and tag.strip()
        ]
        if isinstance(payload.get("tags"), list)
        else [],
        raw=payload,
    )


def _summary(payload: dict[str, Any]) -> str | None:
    """Read a caller-supplied summary without truncating it to a label.

    Summaries are long-form by design, so the short-field cap used for
    identifiers would silently defeat the anti-bloat length policy.
    """
    for key in ("summary", "transcriptSummary", "transcript_summary"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:65_000]
    return None


def _text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_MAX_TEXT]
    return None


def _timestamp(payload: dict[str, Any]) -> str:
    value = payload.get("timestamp")
    if isinstance(value, str) and value.strip():
        return value.strip()[:64]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Copilot camelCase payloads use Unix milliseconds.
        try:
            moment = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return _now()
        return moment.isoformat().replace("+00:00", "Z")
    return _now()


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


class HookDispatcher:
    """Receive host lifecycle events and run allow-listed handlers.

    Handlers are declared in the canonical registry, so every host that can
    reach this server observes the same behavior for the same event.
    """

    def __init__(
        self,
        registry: Registry,
        executor: SkillExecutor,
        state: StateStore,
    ) -> None:
        self.registry = registry
        self.executor = executor
        self.state = state

    def events(self) -> dict[str, Any]:
        """Report canonical events and the handlers configured for each."""
        configured = self.registry.hooks()
        return {
            "events": [
                {"event": name, "handlers": list(configured.get(name, ()))}
                for name in CANONICAL_EVENTS
            ],
            "rootSessionsOnly": sorted(self.registry.hook_root_only_events()),
        }

    def dispatch(self, event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Record a lifecycle event and run its handlers.

        Returns a response both hosts understand. Handler failures are
        contained so a hook never breaks the agent session that fired it.
        """
        hook_event = normalize(event_name, payload)
        root_only = hook_event.event in self.registry.hook_root_only_events()

        # Anti-recursion: a sub-agent must not trigger session-level work,
        # otherwise summarizing a session spawns agents that summarize
        # themselves.
        if root_only and hook_event.is_subagent:
            logger.info(
                "Skipped sub-agent hook",
                extra={
                    "fields": {
                        "event": hook_event.event,
                        "agentType": hook_event.agent_type,
                    }
                },
            )
            return self._response(hook_event, skipped="sub-agent", results=[])

        recorded = self.state.record_hook_event(
            event=hook_event.event,
            session_id=hook_event.session_id,
            payload=hook_event.to_payload(),
        )
        if not recorded["stored"]:
            return self._response(hook_event, skipped=recorded["reason"], results=[])

        results = self._run_handlers(hook_event)
        return self._response(hook_event, skipped=None, results=results)

    def _run_handlers(self, hook_event: HookEvent) -> list[dict[str, Any]]:
        handlers = self.registry.hooks().get(hook_event.event, [])
        results: list[dict[str, Any]] = []
        for reference in handlers:
            try:
                output = self.executor.run_reference(reference, hook_event.to_payload())
                results.append({"handler": reference, "status": "ok", "output": output})
            except (RegistryError, ValueError, TypeError, OSError) as exc:
                # A failing handler must never abort the agent's session.
                logger.warning(
                    "Hook handler failed",
                    extra={
                        "fields": {
                            "event": hook_event.event,
                            "handler": reference,
                            "error": str(exc),
                        }
                    },
                )
                results.append(
                    {"handler": reference, "status": "error", "error": str(exc)}
                )
        return results

    @staticmethod
    def _response(
        hook_event: HookEvent,
        skipped: str | None,
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build one response body that both hosts accept.

        Context is published under the Copilot key and the Claude
        `hookSpecificOutput` key, because each host ignores keys it does
        not recognize.
        """
        response: dict[str, Any] = {
            "event": hook_event.event,
            "sessionId": hook_event.session_id,
            "handled": skipped is None,
            "results": results,
        }
        if skipped is not None:
            response["skipped"] = skipped
            return response

        context = "\n\n".join(
            str(item["output"]["additionalContext"])
            for item in results
            if item["status"] == "ok"
            and isinstance(item.get("output"), dict)
            and isinstance(item["output"].get("additionalContext"), str)
            and item["output"]["additionalContext"].strip()
        )
        if context:
            response["additionalContext"] = context
            response["hookSpecificOutput"] = {
                "hookEventName": hook_event.source_event,
                "additionalContext": context,
            }
        return response
