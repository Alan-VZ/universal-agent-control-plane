from pathlib import Path

import pytest

from universal_agent_control_plane.registry import Registry, RegistryError


REGISTRY_ROOT = Path(__file__).resolve().parents[1] / "registry"


def test_registry_is_valid() -> None:
    result = Registry(REGISTRY_ROOT).validate()
    assert result == {"valid": True, "errors": []}


def test_default_profile_resolves_instruction_and_skill() -> None:
    registry = Registry(REGISTRY_ROOT)
    assert "Unified Agent Instructions" in registry.instructions()
    assert [skill.name for skill in registry.skills()] == ["example-skill"]


def test_search_returns_matching_documents() -> None:
    results = Registry(REGISTRY_ROOT).search("deterministic")
    assert results
    assert results[0]["path"] == "instructions/global.md"


def test_path_traversal_is_rejected() -> None:
    registry = Registry(REGISTRY_ROOT)
    with pytest.raises(RegistryError, match="Invalid skill name"):
        registry.skill_document("../manifest.yaml")
