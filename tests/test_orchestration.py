from pathlib import Path

from universal_agent_control_plane.execution import SkillExecutor
from universal_agent_control_plane.orchestration import Orchestrator
from universal_agent_control_plane.registry import Registry


REGISTRY_ROOT = Path(__file__).resolve().parents[1] / "registry"


def test_broadcast_executes_the_skill_once_per_recipient() -> None:
    orchestrator = Orchestrator(SkillExecutor(Registry(REGISTRY_ROOT)))
    result = orchestrator.route("broadcast", "example-skill", {"name": "Alan"})
    assert result["recipients"] == ["claude", "copilot", "other"]
    assert result["delivery"] == "per-recipient-executions"
    assert result["succeeded"] == ["claude", "copilot", "other"]
    assert result["failed"] == []
    for recipient in result["recipients"]:
        assert (
            result["executions"][recipient]["result"]
            == "Hello Alan, the shared skill is active."
        )


def test_single_target_still_executes_once() -> None:
    orchestrator = Orchestrator(SkillExecutor(Registry(REGISTRY_ROOT)))
    result = orchestrator.route("claude", "example-skill", {"name": "Alan"})
    assert result["recipients"] == ["claude"]
    assert result["succeeded"] == ["claude"]
    assert result["executions"]["claude"]["result"] == (
        "Hello Alan, the shared skill is active."
    )


def test_broadcast_reports_per_recipient_failures_without_aborting() -> None:
    orchestrator = Orchestrator(SkillExecutor(Registry(REGISTRY_ROOT)))
    result = orchestrator.route("broadcast", "unknown-skill", {"name": "Alan"})
    assert result["recipients"] == ["claude", "copilot", "other"]
    assert result["succeeded"] == []
    assert result["failed"] == ["claude", "copilot", "other"]
    assert result["executions"] == {}
    assert all(recipient in result["errors"] for recipient in result["recipients"])
