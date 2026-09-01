import os
import sys
from pathlib import Path

import pytest

from universal_agent_control_plane.execution import SkillExecutor
from universal_agent_control_plane.registry import Registry, RegistryError


REGISTRY_ROOT = Path(__file__).resolve().parents[1] / "registry"


def test_allow_listed_skill_runs() -> None:
    result = SkillExecutor(Registry(REGISTRY_ROOT)).run(
        "example-skill",
        {"name": "Alan"},
    )
    assert result == {
        "skill": "example-skill",
        "result": "Hello Alan, the shared skill is active.",
    }


def test_unknown_skill_cannot_select_a_module() -> None:
    executor = SkillExecutor(Registry(REGISTRY_ROOT))
    with pytest.raises(RegistryError, match="no allow-listed runner"):
        executor.run("os", {})


def test_runner_module_reloads_after_source_change(tmp_path, monkeypatch) -> None:
    module_path = tmp_path / "reloadable_runner.py"
    module_path.write_text("VALUE = 'first'\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    executor = SkillExecutor(Registry(REGISTRY_ROOT))

    first = executor._load_or_reload_module("reloadable_runner")
    assert getattr(first, "VALUE") == "first"
    initial_mtime = module_path.stat().st_mtime_ns
    module_path.write_text("VALUE = 'second'\n", encoding="utf-8")
    updated_mtime = initial_mtime + 1_000_000_000
    os.utime(module_path, ns=(updated_mtime, updated_mtime))

    second = executor._load_or_reload_module("reloadable_runner")
    assert getattr(second, "VALUE") == "second"
    sys.modules.pop("reloadable_runner", None)
