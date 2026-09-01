import pytest
from fastapi.testclient import TestClient

from universal_agent_control_plane.api import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_skills(client: TestClient) -> None:
    health = client.get("/health")
    skills = client.get("/skills")
    assert health.status_code == 200
    assert health.json()["registry"]["valid"] is True
    assert skills.json()["skills"][0]["name"] == "example-skill"


def test_copilot_wrapper_and_orchestration(client: TestClient) -> None:
    skill = client.post(
        "/copilot/skill",
        json={"skill": "example-skill", "payload": {"name": "Alan"}},
    )
    routed = client.post(
        "/orchestrate",
        json={
            "target": "claude",
            "skill": "example-skill",
            "payload": {"name": "Alan"},
        },
    )
    assert skill.status_code == 200
    assert skill.json()["result"] == "Hello Alan, the shared skill is active."
    assert routed.json()["recipients"] == ["claude"]


def test_unknown_skill_is_a_client_error(client: TestClient) -> None:
    response = client.post(
        "/execute",
        json={"skill": "not-installed", "payload": {}},
    )
    assert response.status_code == 400
