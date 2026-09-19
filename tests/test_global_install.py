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

    codex = (installer.paths.home / ".codex" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    codex_skill_link = installer.paths.home / ".codex" / "skills" / "example-skill"

    assert "@uacp-registry/instructions/global.md" in claude
    assert "../../.claude/uacp-registry/instructions/global.md" in copilot
    assert "../.claude/uacp-registry/instructions/global.md" in codex
    assert skill_link.resolve() == (
        PROJECT_ROOT / "registry" / "skills" / "example-skill"
    ).resolve()
    assert codex_skill_link.resolve() == (
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
        "codex": True,
    }
    assert installer.status()["mcp"]["codex"] is True


def test_global_install_codex_mcp_config_is_toml(tmp_path: Path) -> None:
    installer = make_installer(tmp_path)
    installer.install(configure_claude_mcp=False)

    config_path = installer.paths.home / ".codex" / "config.toml"
    text = config_path.read_text(encoding="utf-8")

    assert f"[mcp_servers.{SERVER_NAME}]" in text
    assert f"[mcp_servers.{SERVER_NAME}.env]" in text
    assert "command = " in text


def test_global_install_codex_mcp_preserves_existing_toml(tmp_path: Path) -> None:
    installer = make_installer(tmp_path)
    config_path = installer.paths.home / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        '[mcp_servers.existing]\ncommand = "safe"\n',
        encoding="utf-8",
    )

    installer.install(configure_claude_mcp=False)
    text = config_path.read_text(encoding="utf-8")

    assert '[mcp_servers.existing]\ncommand = "safe"' in text
    assert f"[mcp_servers.{SERVER_NAME}]" in text


def test_global_install_codex_hooks_are_merged_and_idempotent(tmp_path: Path) -> None:
    installer = make_installer(tmp_path)
    hooks_path = installer.paths.home / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(
        json.dumps({"hooks": {"SessionEnd": [{"hooks": [{"command": "keep-me"}]}]}}),
        encoding="utf-8",
    )

    installer.install(configure_claude_mcp=False)
    first = json.loads(hooks_path.read_text(encoding="utf-8"))
    installer.install(configure_claude_mcp=False)
    second = json.loads(hooks_path.read_text(encoding="utf-8"))

    assert first == second
    session_end_groups = first["hooks"]["SessionEnd"]
    assert any(
        group.get("hooks", [{}])[0].get("command") == "keep-me"
        for group in session_end_groups
    )
    assert any(
        "universal_agent_control_plane.cli" in group.get("hooks", [{}])[0].get(
            "command", ""
        )
        for group in session_end_groups
    )
    assert installer.status()["hooks"]["codex"] is True


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
    codex_file = installer.paths.home / ".codex" / "AGENTS.md"
    codex_file.parent.mkdir(parents=True)
    codex_file.write_text("# Personal codex notes\n\nKeep this too.\n", encoding="utf-8")
    codex_config = installer.paths.home / ".codex" / "config.toml"
    codex_config.write_text('[mcp_servers.existing]\ncommand = "safe"\n', encoding="utf-8")
    installer.install(configure_claude_mcp=False)

    result = installer.uninstall()
    claude_text = claude_file.read_text(encoding="utf-8")
    codex_text = codex_file.read_text(encoding="utf-8")
    vscode_mcp = json.loads(
        (installer.paths.vscode_user / "mcp.json").read_text(encoding="utf-8")
    )
    codex_config_text = codex_config.read_text(encoding="utf-8")

    assert result["uninstalled"] is True
    assert claude_text == "# Personal\n\nKeep this.\n"
    assert codex_text == "# Personal codex notes\n\nKeep this too.\n"
    assert SERVER_NAME not in vscode_mcp["servers"]
    assert '[mcp_servers.existing]\ncommand = "safe"' in codex_config_text
    assert f"[mcp_servers.{SERVER_NAME}]" not in codex_config_text
    assert not (
        installer.paths.home / ".claude" / "skills" / "example-skill"
    ).exists()
    assert not (
        installer.paths.home / ".codex" / "skills" / "example-skill"
    ).exists()
