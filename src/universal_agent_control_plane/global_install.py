from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .registry import Registry

SERVER_NAME = "universal-agent-control-plane"
MANAGED_START = "<!-- uacp:start -->"
MANAGED_END = "<!-- uacp:end -->"


class InstallError(RuntimeError):
    """Raised when global configuration cannot be updated safely."""


@dataclass(frozen=True)
class InstallPaths:
    home: Path
    vscode_user: Path

    @classmethod
    def current(cls, home: Path | None = None, vscode_user: Path | None = None) -> "InstallPaths":
        resolved_home = (home or Path.home()).resolve()
        if vscode_user is not None:
            resolved_vscode = vscode_user.resolve()
        elif os.name == "nt":
            appdata = os.environ.get("APPDATA")
            if not appdata:
                raise InstallError("APPDATA is required to locate VS Code user configuration")
            resolved_vscode = (Path(appdata) / "Code" / "User").resolve()
        else:
            resolved_vscode = (resolved_home / ".config" / "Code" / "User").resolve()
        return cls(home=resolved_home, vscode_user=resolved_vscode)


class GlobalInstaller:
    def __init__(
        self,
        project_root: Path,
        python_executable: Path,
        paths: InstallPaths | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.python_executable = python_executable.resolve()
        self.paths = paths or InstallPaths.current()
        self.registry_root = self.project_root / "registry"
        self.registry = Registry(self.registry_root)

    def install(self, configure_claude_mcp: bool = True) -> dict[str, Any]:
        validation = self.registry.validate()
        if not validation["valid"]:
            raise InstallError("; ".join(validation["errors"]))
        if not self.python_executable.is_file():
            raise InstallError(f"Python executable does not exist: {self.python_executable}")

        links = self._install_registry_and_skills()
        instruction_files = self._install_instructions()
        mcp_files = self._install_mcp_configs()
        hook_files = self._install_hooks()
        claude_mcp = self._configure_claude_mcp() if configure_claude_mcp else {
            "configured": False,
            "reason": "skipped",
        }
        return {
            "installed": True,
            "canonicalRegistry": str(self.registry_root),
            "instructions": instruction_files,
            "skillLinks": links,
            "mcpConfigs": mcp_files,
            "hooks": hook_files,
            "claudeMcp": claude_mcp,
        }

    def status(self) -> dict[str, Any]:
        expected_skills = [skill.name for skill in self.registry.skills()]
        skill_status: dict[str, dict[str, bool]] = {}
        for name in expected_skills:
            target = (self.registry_root / "skills" / name).resolve()
            skill_status[name] = {
                scope: self._same_target(root / name, target)
                for scope, root in self._skill_roots().items()
            }
        server = self._server_config()
        return {
            "canonicalRegistry": str(self.registry_root),
            "pythonExists": self.python_executable.is_file(),
            "instructions": {
                "copilot": (
                    self.paths.home
                    / ".copilot"
                    / "instructions"
                    / "uacp-global.instructions.md"
                ).is_file(),
                "claude": self._managed_block_present(
                    self.paths.home / ".claude" / "CLAUDE.md"
                ),
            },
            "skills": skill_status,
            "mcp": {
                "vscode": self._json_server_matches(
                    self.paths.vscode_user / "mcp.json", server
                ),
                "copilotAgentHost": self._json_server_matches(
                    self.paths.home / ".copilot" / "mcp-config.json", server
                ),
                "claudeCliAvailable": shutil.which("claude") is not None,
            },
            "hooks": {
                "events": self._hook_events(),
                "copilot": (
                    self.paths.home / ".copilot" / "hooks" / f"{SERVER_NAME}.json"
                ).is_file(),
                "claude": self._claude_hooks_installed(),
            },
        }

    def plan(self) -> dict[str, Any]:
        skills = [skill.name for skill in self.registry.skills()]
        conflicts: list[str] = []
        for skill in self.registry.skills():
            target = skill.path.parent.resolve()
            for root in self._skill_roots().values():
                candidate = root / skill.name
                if (
                    (candidate.exists() or candidate.is_symlink())
                    and not self._same_target(candidate, target)
                ):
                    conflicts.append(str(candidate))
        return {
            "wouldInstall": True,
            "canonicalRegistry": str(self.registry_root),
            "instructions": [
                str(
                    self.paths.home
                    / ".copilot"
                    / "instructions"
                    / "uacp-global.instructions.md"
                ),
                str(self.paths.home / ".claude" / "CLAUDE.md"),
            ],
            "skills": skills,
            "mcpConfigs": [
                str(self.paths.vscode_user / "mcp.json"),
                str(self.paths.home / ".copilot" / "mcp-config.json"),
            ],
            "hooks": [
                str(self.paths.home / ".copilot" / "hooks" / f"{SERVER_NAME}.json"),
                str(self.paths.home / ".claude" / "settings.json"),
            ],
            "hookEvents": self._hook_events(),
            "conflicts": conflicts,
        }

    def uninstall(self) -> dict[str, Any]:
        removed: list[str] = []
        for skill in self.registry.skills():
            target = skill.path.parent.resolve()
            for root in self._skill_roots().values():
                candidate = root / skill.name
                if self._same_target(candidate, target):
                    self._remove_directory_link(candidate)
                    removed.append(str(candidate))

        registry_link = self.paths.home / ".claude" / "uacp-registry"
        if self._same_target(registry_link, self.registry_root):
            self._remove_directory_link(registry_link)
            removed.append(str(registry_link))

        copilot_instruction = (
            self.paths.home
            / ".copilot"
            / "instructions"
            / "uacp-global.instructions.md"
        )
        if copilot_instruction.is_file():
            copilot_instruction.unlink()
            removed.append(str(copilot_instruction))

        claude_file = self.paths.home / ".claude" / "CLAUDE.md"
        if self._remove_managed_block(claude_file):
            removed.append(f"{claude_file} (managed block)")

        for path in (
            self.paths.vscode_user / "mcp.json",
            self.paths.home / ".copilot" / "mcp-config.json",
        ):
            if self._remove_json_server(path):
                removed.append(f"{path} ({SERVER_NAME})")

        copilot_hooks = self.paths.home / ".copilot" / "hooks" / f"{SERVER_NAME}.json"
        if copilot_hooks.is_file():
            copilot_hooks.unlink()
            removed.append(str(copilot_hooks))

        if self._remove_claude_hooks():
            removed.append(f"{self.paths.home / '.claude' / 'settings.json'} (hooks)")
        return {
            "uninstalled": True,
            "removed": removed,
            "claudeMcp": {
                "removed": False,
                "reason": (
                    "Run 'claude mcp remove universal-agent-control-plane "
                    "--scope user' if it was registered."
                ),
            },
        }

    def _remove_claude_hooks(self) -> bool:
        """Remove only the hook groups this installer created."""
        path = self.paths.home / ".claude" / "settings.json"
        if not path.is_file():
            return False
        document = self._read_json(path, {})
        hooks = document.get("hooks")
        if not isinstance(hooks, dict):
            return False
        changed = False
        for event in list(hooks):
            groups = hooks[event]
            if not isinstance(groups, list):
                continue
            remaining = [
                group for group in groups if not self._is_managed_group(group)
            ]
            if len(remaining) != len(groups):
                changed = True
                if remaining:
                    hooks[event] = remaining
                else:
                    del hooks[event]
        if not changed:
            return False
        if hooks:
            document["hooks"] = hooks
        else:
            document.pop("hooks", None)
        self._write_json(path, document)
        return True

    def _install_registry_and_skills(self) -> list[str]:
        registry_link = self.paths.home / ".claude" / "uacp-registry"
        self._ensure_directory_link(registry_link, self.registry_root)

        installed: list[str] = []
        for skill in self.registry.skills():
            target = skill.path.parent.resolve()
            for scope, root in self._skill_roots().items():
                link = root / skill.name
                self._ensure_directory_link(link, target)
                installed.append(f"{scope}:{link}")
        return installed

    def _install_instructions(self) -> list[str]:
        copilot_file = (
            self.paths.home
            / ".copilot"
            / "instructions"
            / "uacp-global.instructions.md"
        )
        copilot_content = """---
applyTo: "**"
description: Universal instructions shared by all projects and supported agents.
---

# Universal Agent Instructions

Read and follow the canonical [global instructions](../../.claude/uacp-registry/instructions/global.md).

Project-level instructions remain additive and may specialize these global defaults.
"""
        self._write_text(copilot_file, copilot_content)

        claude_file = self.paths.home / ".claude" / "CLAUDE.md"
        managed = (
            f"{MANAGED_START}\n"
            "# Universal Agent Control Plane\n\n"
            "@uacp-registry/instructions/global.md\n"
            f"{MANAGED_END}"
        )
        self._upsert_managed_block(claude_file, managed)
        return [str(copilot_file), str(claude_file)]

    def _install_mcp_configs(self) -> list[str]:
        server = self._server_config()
        files = [
            self.paths.vscode_user / "mcp.json",
            self.paths.home / ".copilot" / "mcp-config.json",
        ]
        for path in files:
            document = self._read_json(path, {"inputs": [], "servers": {}})
            servers = document.setdefault("servers", {})
            if not isinstance(servers, dict):
                raise InstallError(f"'servers' must be an object: {path}")
            servers[SERVER_NAME] = server
            self._write_json(path, document)
        return [str(path) for path in files]

    def _claude_hooks_installed(self) -> bool:
        path = self.paths.home / ".claude" / "settings.json"
        try:
            document = self._read_json(path, {})
        except InstallError:
            return False
        hooks = document.get("hooks")
        if not isinstance(hooks, dict):
            return False
        return any(
            isinstance(groups, list)
            and any(self._is_managed_group(group) for group in groups)
            for groups in hooks.values()
        )

    def _install_hooks(self) -> list[str]:
        """Write managed hook configuration for both hosts.

        Copilot loads its own hook file, and Claude Code reads hooks from
        its user settings. Both are pointed at the same CLI entry point, so
        one registry drives identical behavior on either host.
        """
        written: list[str] = []

        copilot_path = self.paths.home / ".copilot" / "hooks" / f"{SERVER_NAME}.json"
        self._write_json(copilot_path, self._copilot_hooks())
        written.append(str(copilot_path))

        claude_settings = self.paths.home / ".claude" / "settings.json"
        document = self._read_json(claude_settings, {})
        existing = document.get("hooks")
        if existing is not None and not isinstance(existing, dict):
            raise InstallError(f"'hooks' must be an object: {claude_settings}")
        merged = dict(existing or {})
        for event, entries in self._claude_hooks().items():
            unmanaged = [
                group
                for group in merged.get(event, [])
                if not self._is_managed_group(group)
            ]
            merged[event] = unmanaged + entries
        document["hooks"] = merged
        self._write_json(claude_settings, document)
        written.append(str(claude_settings))
        return written

    def _hook_events(self) -> list[str]:
        return sorted(self.registry.hooks())

    def _hook_command(self, event: str) -> list[str]:
        return [
            str(self.python_executable),
            "-m",
            "universal_agent_control_plane.cli",
            "hook",
            event,
        ]

    def _hook_env(self) -> dict[str, str]:
        return {
            "PYTHONPATH": str(self.project_root / "src"),
            "UACP_REGISTRY_ROOT": str(self.registry_root),
            "UACP_DATA_DIR": str(self.project_root / ".data"),
        }

    def _copilot_hooks(self) -> dict[str, Any]:
        # Copilot maps camelCase event names to camelCase payload fields.
        names = {
            "session_start": "sessionStart",
            "session_end": "sessionEnd",
            "user_prompt": "userPromptSubmitted",
            "pre_tool_use": "preToolUse",
            "post_tool_use": "postToolUse",
            "subagent_start": "subagentStart",
            "subagent_stop": "subagentStop",
        }
        hooks: dict[str, Any] = {}
        for event in self._hook_events():
            host_event = names.get(event)
            if host_event is None:
                continue
            command = self._hook_command(event)
            hooks[host_event] = [
                {
                    # `exec` runs the interpreter directly with no shell, which
                    # keeps Windows paths containing spaces intact.
                    "type": "command",
                    "exec": command[0],
                    "args": command[1:],
                    "env": self._hook_env(),
                    "timeoutSec": 10,
                }
            ]
        return {"version": 1, "hooks": hooks}

    def _claude_hooks(self) -> dict[str, list[dict[str, Any]]]:
        # Claude Code uses PascalCase event names and matcher groups.
        names = {
            "session_start": "SessionStart",
            "session_end": "SessionEnd",
            "user_prompt": "UserPromptSubmit",
            "pre_tool_use": "PreToolUse",
            "post_tool_use": "PostToolUse",
            "subagent_start": "SubagentStart",
            "subagent_stop": "SubagentStop",
        }
        hooks: dict[str, list[dict[str, Any]]] = {}
        for event in self._hook_events():
            host_event = names.get(event)
            if host_event is None:
                continue
            command = self._hook_command(event)
            handler: dict[str, Any] = {
                "type": "command",
                "command": command[0],
                "args": command[1:],
                "statusMessage": f"UACP {event}",
            }
            if host_event == "SessionEnd":
                # SessionEnd handlers share a 1.5 second budget by default.
                # Running in the background keeps session shutdown responsive.
                handler["async"] = True
            hooks[host_event] = [{"hooks": [handler]}]
        return hooks

    @staticmethod
    def _is_managed_group(group: Any) -> bool:
        if not isinstance(group, dict):
            return False
        handlers = group.get("hooks")
        if not isinstance(handlers, list):
            return False
        return any(
            isinstance(handler, dict)
            and isinstance(handler.get("args"), list)
            and "universal_agent_control_plane.cli" in handler["args"]
            for handler in handlers
        )

    def _configure_claude_mcp(self) -> dict[str, Any]:
        claude = shutil.which("claude")
        if claude is None:
            return {
                "configured": False,
                "reason": "Claude CLI is not installed; instructions and skills are ready.",
                "command": self.claude_install_command(),
            }
        definition = json.dumps(self._claude_server_config(), separators=(",", ":"))
        result = subprocess.run(
            [
                claude,
                "mcp",
                "add-json",
                SERVER_NAME,
                definition,
                "--scope",
                "user",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise InstallError(f"Claude MCP registration failed: {message}")
        return {"configured": True, "message": result.stdout.strip()}

    def claude_install_command(self) -> str:
        definition = json.dumps(self._claude_server_config(), separators=(",", ":"))
        return (
            f"claude mcp add-json {SERVER_NAME} "
            f"'{definition}' --scope user"
        )

    def _server_config(self) -> dict[str, Any]:
        return {
            "type": "stdio",
            "command": str(self.python_executable),
            "args": ["-m", "universal_agent_control_plane.server"],
            "cwd": str(self.project_root),
            "env": {
                "PYTHONPATH": str(self.project_root / "src"),
                "UACP_REGISTRY_ROOT": str(self.registry_root),
                "UACP_DATA_DIR": str(self.project_root / ".data"),
            },
        }

    def _claude_server_config(self) -> dict[str, Any]:
        config = self._server_config()
        config.pop("type")
        return config

    def _skill_roots(self) -> dict[str, Path]:
        return {
            "copilot": self.paths.home / ".copilot" / "skills",
            "claude": self.paths.home / ".claude" / "skills",
            "agents": self.paths.home / ".agents" / "skills",
        }

    def _ensure_directory_link(self, link: Path, target: Path) -> None:
        target = target.resolve()
        if not target.is_dir():
            raise InstallError(f"Link target is not a directory: {target}")
        if link.exists() or link.is_symlink():
            if self._same_target(link, target):
                return
            raise InstallError(f"Refusing to replace existing path: {link}")
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            result = subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0 or not self._same_target(link, target):
                message = result.stderr.strip() or result.stdout.strip()
                raise InstallError(f"Cannot create directory link {link}: {message}")

    @staticmethod
    def _remove_directory_link(path: Path) -> None:
        if path.is_symlink():
            path.unlink()
        elif os.name == "nt":
            os.rmdir(path)
        else:
            raise InstallError(f"Refusing to remove non-link directory: {path}")

    @staticmethod
    def _same_target(link: Path, target: Path) -> bool:
        try:
            return link.resolve() == target.resolve()
        except OSError:
            return False

    @staticmethod
    def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default.copy()
        try:
            parsed = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstallError(f"Cannot parse JSON configuration: {path}") from exc
        if not isinstance(parsed, dict):
            raise InstallError(f"JSON configuration must be an object: {path}")
        return parsed

    @staticmethod
    def _write_json(path: Path, document: dict[str, Any]) -> None:
        GlobalInstaller._write_text(
            path,
            json.dumps(document, indent=2, ensure_ascii=True) + "\n",
        )

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _upsert_managed_block(path: Path, block: str) -> None:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        start = existing.find(MANAGED_START)
        end = existing.find(MANAGED_END)
        if (start == -1) != (end == -1):
            raise InstallError(f"Managed instruction markers are incomplete: {path}")
        if start == -1:
            updated = f"{existing.rstrip()}\n\n{block}\n".lstrip()
        else:
            end += len(MANAGED_END)
            updated = f"{existing[:start]}{block}{existing[end:]}"
        GlobalInstaller._write_text(path, updated)

    @staticmethod
    def _remove_managed_block(path: Path) -> bool:
        if not path.is_file():
            return False
        existing = path.read_text(encoding="utf-8")
        start = existing.find(MANAGED_START)
        end = existing.find(MANAGED_END)
        if start == -1 and end == -1:
            return False
        if start == -1 or end == -1:
            raise InstallError(f"Managed instruction markers are incomplete: {path}")
        end += len(MANAGED_END)
        updated = f"{existing[:start]}{existing[end:]}".strip()
        if updated:
            GlobalInstaller._write_text(path, updated + "\n")
        else:
            path.unlink()
        return True

    @staticmethod
    def _managed_block_present(path: Path) -> bool:
        if not path.is_file():
            return False
        text = path.read_text(encoding="utf-8")
        return MANAGED_START in text and MANAGED_END in text

    @staticmethod
    def _json_server_matches(path: Path, expected: dict[str, Any]) -> bool:
        try:
            document = GlobalInstaller._read_json(path, {})
        except InstallError:
            return False
        servers = document.get("servers")
        return isinstance(servers, dict) and servers.get(SERVER_NAME) == expected

    def _remove_json_server(self, path: Path) -> bool:
        if not path.is_file():
            return False
        document = self._read_json(path, {})
        servers = document.get("servers")
        if not isinstance(servers, dict) or SERVER_NAME not in servers:
            return False
        if servers[SERVER_NAME] != self._server_config():
            raise InstallError(
                f"Refusing to remove modified MCP server configuration: {path}"
            )
        del servers[SERVER_NAME]
        self._write_json(path, document)
        return True
