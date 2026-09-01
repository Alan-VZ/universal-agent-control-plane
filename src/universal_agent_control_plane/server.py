from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from .execution import SkillExecutor
from .logging_config import configure_logging
from .orchestration import AgentTarget, Orchestrator
from .registry import Registry, RegistryError
from .storage import StateStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_ROOT = Path(os.environ.get("UACP_REGISTRY_ROOT", PROJECT_ROOT / "registry"))
DATA_DIR = Path(os.environ.get("UACP_DATA_DIR", PROJECT_ROOT / ".data"))

registry = Registry(REGISTRY_ROOT)
state = StateStore(DATA_DIR)
executor = SkillExecutor(registry)
orchestrator = Orchestrator(executor)
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


@mcp.tool()
def registry_validate() -> dict[str, Any]:
    """Validate the canonical registry and return actionable errors."""
    return registry.validate()


@mcp.tool()
def registry_resolve(profile: str = "default") -> dict[str, Any]:
    """Resolve a profile into effective instructions and skill metadata."""
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


@mcp.tool()
def registry_search(query: str) -> list[dict[str, str]]:
    """Search instruction, skill, and prompt documents."""
    return registry.search(query)


@mcp.tool()
def skill_run(skill_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run an allow-listed skill, reloading its implementation after source changes."""
    return executor.run(skill_name, payload)


@mcp.tool()
def orchestrate(
    target: AgentTarget,
    skill_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Route one skill result to an agent target or a broadcast result envelope."""
    return orchestrator.route(target, skill_name, payload)


@mcp.tool()
def state_get(namespace: str, key: str) -> dict[str, Any]:
    """Read a namespaced value from shared local state."""
    return {"namespace": namespace, "key": key, "value": state.get(namespace, key)}


@mcp.tool()
def state_put(namespace: str, key: str, value: Any) -> dict[str, str]:
    """Write a namespaced value to shared local state and audit the mutation."""
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
