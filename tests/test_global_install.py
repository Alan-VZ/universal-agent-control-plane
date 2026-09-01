import json
import sys
from pathlib import Path

import pytest

from universal_agent_control_plane.global_install import (
    GlobalInstaller,
    InstallError,
    InstallPaths,
    SERVER_NAME,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


def make_installer(tmp_path: Path) -> GlobalInstaller:
    return GlobalInstaller(
        PROJECT_ROOT,
        PYTHON,
        InstallPaths(
            home=tmp_path / "home",
            vscode_user=tmp_path / "vscode-user",
        ),
    )


def test_global_install_preserves_existing_mcp_servers(tmp_path: Path) -> None:
    installer = make_installer(tmp_path)
    vscode_mcp = installer.paths.vscode_user / "mcp.json"
    vscode_mcp.parent.mkdir(parents=True)
    vscode_mcp.write_text(
        json.dumps({"inputs": [], "servers": {"existing": {"command": "safe"}}}),
        encoding="utf-8",
    )

    result = installer.install(configure_claude_mcp=False)
    installed = json.loads(vscode_mcp.read_text(encoding="utf-8"))

    assert result["installed"] is True
    assert installed["servers"]["existing"] == {"command": "safe"}
    assert SERVER_NAME in installed["servers"]
    assert installer.status()["mcp"]["vscode"] is True


def test_global_install_uses_canonical_instruction_and_skill_links(
    tmp_path: Path,
) -> None:
    installer = make_installer(tmp_path)
    installer.install(configure_claude_mcp=False)

    claude = (installer.paths.home / ".claude" / "CLAUDE.md").read_text(
        encoding="utf-8"
    )
    copilot = (
        installer.paths.home
        / ".copilot"
        / "instructions"
        / "uacp-global.instructions.md"
    ).read_text(encoding="utf-8")
    skill_link = (
        installer.paths.home / ".claude" / "skills" / "example-skill"
    )

    assert "@uacp-registry/instructions/global.md" in claude
    assert "../../.claude/uacp-registry/instructions/global.md" in copilot
    assert skill_link.resolve() == (
        PROJECT_ROOT / "registry" / "skills" / "example-skill"
    ).resolve()


def test_global_install_is_idempotent(tmp_path: Path) -> None:
    installer = make_installer(tmp_path)
    first = installer.install(configure_claude_mcp=False)
    second = installer.install(configure_claude_mcp=False)
    assert first["instructions"] == second["instructions"]
    assert installer.status()["instructions"] == {
        "copilot": True,
        "claude": True,
    }


def test_global_install_refuses_to_replace_existing_skill(tmp_path: Path) -> None:
    installer = make_installer(tmp_path)
    conflict = (
        installer.paths.home / ".copilot" / "skills" / "example-skill"
    )
    conflict.mkdir(parents=True)
    with pytest.raises(InstallError, match="Refusing to replace"):
        installer.install(configure_claude_mcp=False)


def test_plan_does_not_write_files(tmp_path: Path) -> None:
    installer = make_installer(tmp_path)
    plan = installer.plan()
    assert plan["wouldInstall"] is True
    assert not installer.paths.home.exists()
    assert not installer.paths.vscode_user.exists()


def test_uninstall_removes_only_managed_content(tmp_path: Path) -> None:
    installer = make_installer(tmp_path)
    claude_file = installer.paths.home / ".claude" / "CLAUDE.md"
    claude_file.parent.mkdir(parents=True)
    claude_file.write_text("# Personal\n\nKeep this.\n", encoding="utf-8")
    installer.install(configure_claude_mcp=False)

    result = installer.uninstall()
    claude_text = claude_file.read_text(encoding="utf-8")
    vscode_mcp = json.loads(
        (installer.paths.vscode_user / "mcp.json").read_text(encoding="utf-8")
    )

    assert result["uninstalled"] is True
    assert claude_text == "# Personal\n\nKeep this.\n"
    assert SERVER_NAME not in vscode_mcp["servers"]
    assert not (
        installer.paths.home / ".claude" / "skills" / "example-skill"
    ).exists()
