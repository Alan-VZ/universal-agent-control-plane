from __future__ import annotations

import logging
from typing import Any, Literal

from .execution import SkillExecutor

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
        execution = self.executor.run(skill_name, payload)
        return {
            "target": target,
            "recipients": recipients,
            "execution": execution,
            "delivery": "result-envelope",
        }
