from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .execution import SkillExecutor
from .hooks import HookDispatcher
from .logging_config import configure_logging
from .orchestration import AgentTarget, Orchestrator
from .registry import Registry, RegistryError
from .storage import StateStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_ROOT = Path(os.environ.get("UACP_REGISTRY_ROOT", PROJECT_ROOT / "registry"))
DATA_DIR = Path(os.environ.get("UACP_DATA_DIR", PROJECT_ROOT / ".data"))

registry = Registry(REGISTRY_ROOT)
state = StateStore(DATA_DIR)
executor = SkillExecutor(registry, state)
orchestrator = Orchestrator(executor)
hooks = HookDispatcher(registry, executor, state)
mcp = MCPServer("Universal Agent Control Plane")
logger = logging.getLogger(__name__)


@mcp.resource("registry://manifest")
def registry_manifest() -> dict[str, Any]:
    """Return the canonical registry manifest."""
    return registry.manifest()


@mcp.resource("instructions://effective/{profile}")
def effective_instructions(profile: str) -> str:
    """Return the resolved instructions for a registry profile."""
    return registry.instructions(profile)


@mcp.resource("skills://catalog")
def skill_catalog() -> list[dict[str, str]]:
    """List portable Agent Skills available in the registry."""
    return [
        {"name": skill.name, "description": skill.description}
        for skill in registry.skills()
    ]


@mcp.resource("skills://{name}/manifest")
def skill_manifest(name: str) -> str:
    """Return a skill's SKILL.md document."""
    return registry.skill_document(name)


@mcp.prompt(title="Review code")
def review_code(code: str, language: str = "text") -> str:
    """Create a code-review request using the canonical prompt template."""
    template = registry.prompt_template("code-review")
    return template.replace("{{language}}", language).replace("{{code}}", code)


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def registry_validate() -> dict[str, Any]:
    """Validate the canonical registry and return actionable errors.

    Read-only; makes no changes and has no parameters. Use this before editing
    manifest, skill, or profile files (or in CI) to catch broken profile
    references, missing skill runners, or malformed SKILL.md frontmatter
    before they surface as failures from `registry_resolve` or `skill_run`.
    Do not use it to fetch a profile's content; call `registry_resolve` for
    that once validation passes.

    Returns `{"valid": bool, "errors": [str, ...]}`. Never raises for
    registry problems; validation failures are reported in `errors` instead.
    """
    return registry.validate()


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def registry_resolve(
    profile: Annotated[
        str,
        Field(
            description=(
                "Name of a profile declared under the `profiles:` key in the "
                "registry manifest, e.g. \"default\". Run `registry_validate` "
                "or `registry_search` first if you are unsure which profiles "
                "exist."
            )
        ),
    ] = "default",
) -> dict[str, Any]:
    """Resolve a profile into its effective instructions and skill metadata.

    Use this when an agent needs the complete, ready-to-use configuration for
    a named profile: the merged instructions text plus the list of skills
    (name and description) that profile enables. Use `registry_search`
    instead when you know a keyword but not which profile or document
    contains it; use `skill_run` afterward to actually execute one of the
    returned skills.

    Read-only. Raises an error if the profile is unknown, references a
    skill that does not exist, or its `skills` entry is not a list.

    Returns `{"profile": str, "instructions": str, "skills": [{"name": str,
    "description": str}, ...]}`.
    """
    selected = registry.profile(profile)
    configured_skills = selected.get("skills", [])
    available = {skill.name: skill for skill in registry.skills()}
    if not isinstance(configured_skills, list):
        raise RegistryError(f"Profile skills must be a list: {profile}")
    missing = [name for name in configured_skills if name not in available]
    if missing:
        raise RegistryError(f"Profile references unknown skills: {', '.join(missing)}")
    return {
        "profile": profile,
        "instructions": registry.instructions(profile),
        "skills": [
            {"name": available[name].name, "description": available[name].description}
            for name in configured_skills
        ],
    }


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def registry_search(
    query: Annotated[
        str,
        Field(
            description=(
                "Case-insensitive substring to look for. Matching is a plain "
                "text `in` check against each document's full content (no "
                "wildcards, regex, or tokenization). Must not be empty or "
                "whitespace-only."
            )
        ),
    ],
) -> list[dict[str, str]]:
    """Search instruction, skill, and prompt documents for a keyword.

    Use this read-only tool when you know a keyword or phrase but not which
    profile or document contains it. Use `registry_resolve` instead when you
    already know the profile name and need its complete effective
    configuration. Searches every `*.md` file under the registry's
    `instructions/`, `skills/`, and `prompts/` directories.

    Raises an error if `query` is empty after trimming whitespace.

    Returns a list of `{"path": str, "excerpt": str}` matches, one per
    matching file, ordered by path. An empty list means no document
    contained the query.
    """
    return registry.search(query)


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
)
def skill_run(
    skill_name: Annotated[
        str,
        Field(
            description=(
                "Exact skill name matching a `skills/<name>/SKILL.md` "
                "directory that is registered under the manifest's "
                "`runners:` mapping. Use `registry_resolve` or "
                "`registry_search` to discover valid names; unregistered "
                "or unknown names are rejected before any code runs."
            )
        ),
    ],
    payload: Annotated[
        dict[str, Any],
        Field(
            description=(
                "JSON object of arguments passed through to the skill's "
                "runner function. The accepted fields are defined by each "
                "skill's own SKILL.md document, not by this tool; consult "
                "that document (via the `skills://{name}/manifest` "
                "resource) for the expected shape. Must be a JSON object, "
                "not a list or scalar."
            )
        ),
    ],
) -> dict[str, Any]:
    """Run one allow-listed skill directly, reloading it if its source changed.

    Use this to execute a single named skill once, synchronously, in the
    current process. Use `orchestration_route` instead when the skill must
    run against a specific agent target or be broadcast to every known
    agent. This tool never imports an arbitrary module name supplied by the
    caller: only runners declared in the manifest's allow list can execute.

    Side effects depend entirely on the skill being run; some skills read
    or write shared state, call other tools, or reach external systems.
    Raises an error if `skill_name` is not allow-listed, `payload` is not an
    object, or the skill implementation itself raises.

    Returns `{"skill": str, **<skill's own result fields>}`.
    """
    return executor.run(skill_name, payload)


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
)
def orchestration_route(
    target: Annotated[
        AgentTarget,
        Field(
            description=(
                "Delivery target for the skill run. \"claude\", \"copilot\", "
                "and \"other\" each run the skill exactly once, addressed to "
                "that agent. \"broadcast\" runs the skill independently once "
                "per known agent (\"claude\", \"copilot\", \"other\"); one "
                "recipient's failure does not stop the others."
            )
        ),
    ],
    skill_name: Annotated[
        str,
        Field(
            description=(
                "Exact skill name matching a `skills/<name>/SKILL.md` "
                "directory that is registered under the manifest's "
                "`runners:` mapping, identical in meaning to the "
                "`skill_name` parameter of `skill_run`."
            )
        ),
    ],
    payload: Annotated[
        dict[str, Any],
        Field(
            description=(
                "JSON object of arguments passed through to the skill's "
                "runner function for every recipient. The accepted fields "
                "are defined by each skill's own SKILL.md document; consult "
                "that document (via the `skills://{name}/manifest` "
                "resource) for the expected shape. Must be a JSON object, "
                "not a list or scalar."
            )
        ),
    ],
) -> dict[str, Any]:
    """Route one skill to an agent target, executing it once per recipient.

    Use this instead of `skill_run` whenever the caller needs to address a
    specific agent host or fan out to every known agent with `broadcast`.
    For a single target the skill runs once, synchronously, exactly like
    `skill_run`. For `broadcast` the skill runs independently for each known
    agent in-process; a failure for one recipient is captured and does not
    prevent execution for the others, and execution is not parallelized
    across recipients.

    Side effects depend entirely on the skill being run, same as
    `skill_run`. Raises an error only if `target` is not one of the
    supported values; per-recipient skill failures are captured in the
    response instead of raising.

    Returns `{"target": str, "recipients": [str, ...], "executions":
    {recipient: <skill result>, ...}, "errors": {recipient: str, ...},
    "delivery": "per-recipient-executions", "succeeded": [str, ...],
    "failed": [str, ...]}`.
    """
    return orchestrator.route(target, skill_name, payload)


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def hook_list() -> dict[str, Any]:
    """List canonical lifecycle events and their configured handlers.

    Read-only; makes no changes and has no parameters. Use this to discover
    which lifecycle events (e.g. `session_start`, `pre_tool_use`) exist and
    which handler references the registry runs for each before calling
    `hook_emit` to fire one. See `hook_emit` to actually dispatch an event.

    Returns `{"events": [{"event": str, "handlers": [str, ...]}, ...],
    "rootSessionsOnly": [str, ...]}`, where `rootSessionsOnly` lists events
    that are skipped when raised from a sub-agent session.
    """
    return hooks.events()


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
def hook_emit(
    event: Annotated[
        str,
        Field(
            description=(
                "Lifecycle event name. Accepts the canonical snake_case "
                "names returned by `hook_list` (e.g. \"session_start\", "
                "\"pre_tool_use\") as well as the camelCase/PascalCase "
                "spellings used by Copilot and Claude Code hosts (e.g. "
                "\"SessionStart\"), which are normalized automatically."
            )
        ),
    ],
    payload: Annotated[
        dict[str, Any],
        Field(
            description=(
                "JSON object describing the event context, typically "
                "including a session identifier and agent type field so the "
                "dispatcher can normalize and deduplicate it. Serialized "
                "size must not exceed 64 KiB."
            )
        ),
    ],
) -> dict[str, Any]:
    """Dispatch a lifecycle event from any host that cannot call hooks directly.

    Use this when a host or script needs to raise a lifecycle event (such as
    session start/end or a tool-use boundary) without the event arriving
    through the host's native hook mechanism. See `hook_list` first to see
    which events and handlers are configured.

    Idempotent per session: at most one record is stored per
    `(event, session_id)` pair, so repeat delivery of the same event for the
    same session is a no-op rather than re-running handlers. Events raised
    from a sub-agent are silently skipped for events marked
    `rootSessionsOnly` by `hook_list`, to avoid a session-summary hook
    spawning agents that summarize themselves. Handler failures are
    contained and never raise back to the caller. May have external side
    effects if a configured handler does (e.g. writing files, calling other
    tools).

    Returns a response shape both hosts understand, including whether the
    event was newly stored.
    """
    return hooks.dispatch(event, payload)


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def journal_recent(
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=50,
            description=(
                "Maximum number of most-recent session summaries to return, "
                "from 1 to 50 inclusive."
            ),
        ),
    ] = 5,
) -> list[dict[str, Any]]:
    """Return recent session summaries recorded by session-end hooks.

    Read-only. Use this to see what prior sessions accomplished, most
    recent first, typically to give a new session continuity context. Each
    session appears at most once, written once by its `session_end` hook
    handler via `hook_emit`; there is no tool to add or edit entries
    directly.

    Raises an error if `limit` is outside 1-50.

    Returns a list of `{"sessionId": str, "summary": str, "tags": [str,
    ...], "createdAt": str}`, newest first. An empty list means no session
    has been journaled yet.
    """
    return state.recent_journal(limit)


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def state_get(
    namespace: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description=(
                "Namespace the value was stored under, 1-128 characters. "
                "Namespaces are free-form strings (e.g. a project or agent "
                "name) used to keep unrelated keys from colliding."
            ),
        ),
    ],
    key: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description="Key within the namespace, 1-128 characters.",
        ),
    ],
) -> dict[str, Any]:
    """Read a namespaced value from shared local state.

    Use this to fetch a value previously written with `state_put`. Read-only
    and safe to call speculatively; a missing key is not an error.

    Returns `{"namespace": str, "key": str, "value": <stored JSON value> |
    null}`. `value` is `null` both when nothing was ever stored at that
    namespace/key and when the stored value itself is JSON `null`; there is
    no separate "not found" signal.
    """
    return {"namespace": namespace, "key": key, "value": state.get(namespace, key)}


@mcp.tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def state_put(
    namespace: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description=(
                "Namespace to store the value under, 1-128 characters. "
                "Namespaces are free-form strings (e.g. a project or agent "
                "name) used to keep unrelated keys from colliding."
            ),
        ),
    ],
    key: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description="Key within the namespace, 1-128 characters.",
        ),
    ],
    value: Annotated[
        Any,
        Field(
            description=(
                "Any JSON-serializable value (object, array, string, "
                "number, boolean, or null) to store. Its JSON-serialized "
                "form must not exceed 64 KiB."
            )
        ),
    ],
) -> dict[str, str]:
    """Write a namespaced value to shared local state and audit the mutation.

    This is an upsert: writing to an existing `(namespace, key)` pair
    silently overwrites the previous value rather than erroring or merging,
    so the prior value is unrecoverable once overwritten (unless a copy was
    read first with `state_get`). Calling it twice with the same arguments
    leaves state in the same end result (idempotent), but each call is
    still recorded as a separate entry in the local audit log. Local-only:
    no external systems are contacted.

    Raises an error if `namespace` or `key` are empty or exceed 128
    characters, or if the serialized `value` exceeds 64 KiB.
    """
    result = state.put(namespace, key, value)
    logger.info(
        "Updated shared state",
        extra={"fields": {"namespace": namespace, "key": key}},
    )
    return result


def main() -> None:
    configure_logging(DATA_DIR)
    validation = registry.validate()
    if not validation["valid"]:
        raise RegistryError("; ".join(validation["errors"]))
    logger.info(
        "Starting MCP server",
        extra={"fields": {"transport": "stdio", "registry": str(REGISTRY_ROOT)}},
    )
    mcp.run()


if __name__ == "__main__":
    main()
