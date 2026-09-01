from pathlib import Path

from universal_agent_control_plane.execution import SkillExecutor
from universal_agent_control_plane.orchestration import Orchestrator
from universal_agent_control_plane.registry import Registry


REGISTRY_ROOT = Path(__file__).resolve().parents[1] / "registry"


def test_broadcast_returns_an_explicit_result_envelope() -> None:
    orchestrator = Orchestrator(SkillExecutor(Registry(REGISTRY_ROOT)))
    result = orchestrator.route("broadcast", "example-skill", {"name": "Alan"})
    assert result["recipients"] == ["claude", "copilot", "other"]
    assert result["delivery"] == "result-envelope"
    assert result["execution"]["result"] == "Hello Alan, the shared skill is active."
