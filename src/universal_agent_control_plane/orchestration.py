from __future__ import annotations

import logging
from typing import Any, Literal

from .execution import SkillExecutor
from .registry import RegistryError

AgentTarget = Literal["claude", "copilot", "other", "broadcast"]
AGENTS = ("claude", "copilot", "other")
logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, executor: SkillExecutor) -> None:
        self.executor = executor

    def route(
        self,
        target: AgentTarget,
        skill_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if target not in (*AGENTS, "broadcast"):
            raise ValueError(f"Unsupported target: {target}")
        recipients = list(AGENTS) if target == "broadcast" else [target]
        logger.info(
            "Routing skill request",
            extra={
                "fields": {
                    "target": target,
                    "recipients": recipients,
                    "skill": skill_name,
                }
            },
        )
        executions: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        for recipient in recipients:
            try:
                executions[recipient] = self.executor.run(skill_name, payload)
            except (RegistryError, ValueError) as exc:
                errors[recipient] = str(exc)
                logger.warning(
                    "Recipient execution failed",
                    extra={
                        "fields": {
                            "target": target,
                            "recipient": recipient,
                            "skill": skill_name,
                            "error": str(exc),
                        }
                    },
                )
        return {
            "target": target,
            "recipients": recipients,
            "executions": executions,
            "errors": errors,
            "delivery": "per-recipient-executions",
            "succeeded": list(executions),
            "failed": list(errors),
        }
