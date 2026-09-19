from __future__ import annotations

import json
import sys
from pathlib import Path

from universal_agent_control_plane.global_install import GlobalInstaller, InstallPaths

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _installer(tmp_path: Path) -> GlobalInstaller:
    home = tmp_path / "home"
    paths = InstallPaths(home=home, vscode_user=home / "vscode")
    return GlobalInstaller(
        project_root=PROJECT_ROOT,
        paths=paths,
        python_executable=Path(sys.executable),
    )


def test_hook_install_is_idempotent_and_preserves_unmanaged_hooks(
    tmp_path: Path,
) -> None:
    installer = _installer(tmp_path)
    claude_settings = installer.paths.home / ".claude" / "settings.json"
    claude_settings.parent.mkdir(parents=True, exist_ok=True)
    claude_settings.write_text(
        json.dumps(
            {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "mine"}]}]}}
        ),
        encoding="utf-8",
    )

    installer._install_hooks()
    installer._install_hooks()

    document = json.loads(claude_settings.read_text(encoding="utf-8"))
    groups = document["hooks"]["SessionEnd"]
    managed = [group for group in groups if installer._is_managed_group(group)]
    unmanaged = [group for group in groups if not installer._is_managed_group(group)]
    assert len(managed) == 1, "re-running install must not duplicate managed hooks"
    assert len(unmanaged) == 1, "user-authored hooks must survive install"

    copilot = installer.paths.home / ".copilot" / "hooks"
    payload = json.loads(
        (copilot / "universal-agent-control-plane.json").read_text(encoding="utf-8")
    )
    assert payload["version"] == 1
    entry = payload["hooks"]["sessionEnd"][0]
    assert entry["exec"] == sys.executable
    assert entry["args"][-1] == "session_end"

    codex_hooks_path = installer.paths.home / ".codex" / "hooks.json"
    codex_document = json.loads(codex_hooks_path.read_text(encoding="utf-8"))
    codex_groups = codex_document["hooks"]["SessionEnd"]
    codex_managed = [
        group for group in codex_groups if installer._is_managed_codex_group(group)
    ]
    assert len(codex_managed) == 1, "re-running install must not duplicate codex hooks"
    codex_handler = codex_managed[0]["hooks"][0]
    assert codex_handler["type"] == "command"
    assert sys.executable in codex_handler["command"]
    assert codex_handler["async"] is True
    assert codex_handler["timeout"] == 3


def test_uninstall_removes_only_managed_hooks(tmp_path: Path) -> None:
    installer = _installer(tmp_path)
    claude_settings = installer.paths.home / ".claude" / "settings.json"
    claude_settings.parent.mkdir(parents=True, exist_ok=True)
    claude_settings.write_text(
        json.dumps(
            {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "mine"}]}]}}
        ),
        encoding="utf-8",
    )
    installer._install_hooks()

    assert installer.status()["hooks"]["copilot"] is True
    assert installer.status()["hooks"]["claude"] is True
    assert installer.status()["hooks"]["codex"] is True

    installer.uninstall()

    assert not (
        installer.paths.home / ".copilot" / "hooks" / "universal-agent-control-plane.json"
    ).exists()
    document = json.loads(claude_settings.read_text(encoding="utf-8"))
    groups = document["hooks"]["SessionEnd"]
    assert len(groups) == 1
    assert groups[0]["hooks"][0]["command"] == "mine"

    codex_hooks_path = installer.paths.home / ".codex" / "hooks.json"
    assert not codex_hooks_path.exists()
