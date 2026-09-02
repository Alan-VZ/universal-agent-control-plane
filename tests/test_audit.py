from __future__ import annotations

import time
from pathlib import Path

from universal_agent_control_plane.execution import SkillExecutor
from universal_agent_control_plane.registry import Registry
from universal_agent_control_plane.storage import StateStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "src" / "universal_agent_control_plane" / "runners" / "greeting.py"


def test_execution_is_audited_with_the_source_hash(tmp_path: Path) -> None:
    state = StateStore(tmp_path)
    executor = SkillExecutor(Registry(PROJECT_ROOT / "registry"), state)
    executor.run("example-skill", {"name": "Alan"})

    records = state.recent_audit()
    runs = [record for record in records if record["action"] == "skill.run"]
    assert len(runs) == 1
    assert runs[0]["key"].startswith("sha256:")


def test_hot_reload_changes_the_audited_hash(tmp_path: Path) -> None:
    """A reloaded runner must not be auditable as the code it replaced."""
    original = RUNNER.read_bytes()
    state = StateStore(tmp_path)
    executor = SkillExecutor(Registry(PROJECT_ROOT / "registry"), state)
    try:
        executor.run("example-skill", {"name": "Alan"})
        first = state.recent_audit()[0]["key"]

        RUNNER.write_bytes(original + b"\n# reload probe\n")
        # mtime resolution can collide on fast consecutive writes.
        time.sleep(0.01)
        RUNNER.touch()
        executor.run("example-skill", {"name": "Alan"})
        second = state.recent_audit()[0]["key"]
    finally:
        RUNNER.write_bytes(original)

    assert first != second, "audit must distinguish reloaded runner source"
