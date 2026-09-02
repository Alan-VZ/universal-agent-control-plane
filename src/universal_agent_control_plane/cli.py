from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .global_install import GlobalInstaller


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uacp",
        description="Manage the Universal Agent Control Plane",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    install = subcommands.add_parser(
        "install-global",
        help="Install global instructions, skills, and MCP configuration",
    )
    install.add_argument(
        "--skip-claude-mcp",
        action="store_true",
        help="Do not run Claude CLI MCP registration",
    )
    install.add_argument(
        "--dry-run",
        action="store_true",
        help="Show intended destinations and conflicts without writing files",
    )
    sync = subcommands.add_parser(
        "sync-global",
        help="Reconcile managed global files and links with the registry",
    )
    sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Show intended destinations and conflicts without writing files",
    )
    subcommands.add_parser(
        "status",
        help="Check global instruction, skill, and MCP installation",
    )
    subcommands.add_parser(
        "doctor",
        help="Alias for status with installation diagnostics",
    )
    subcommands.add_parser(
        "uninstall-global",
        help="Remove only content and links managed by UACP",
    )
    hook = subcommands.add_parser(
        "hook",
        help="Dispatch a lifecycle event read as JSON on stdin",
    )
    hook.add_argument("event", help="Canonical or host event name, such as session_end")
    return parser


def _run_hook(event: str) -> dict[str, object]:
    """Dispatch a hook delivered on stdin by a host command hook.

    A command hook must never break the session that fired it, so any
    failure is reported as data and the process still exits successfully.
    """
    from .hooks import HookDispatcher, HookError
    from .server import executor, registry, state

    raw = sys.stdin.read().strip()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        return {"handled": False, "error": f"Invalid JSON on stdin: {exc}"}
    if not isinstance(payload, dict):
        return {"handled": False, "error": "Hook payload must be a JSON object"}
    try:
        return HookDispatcher(registry, executor, state).dispatch(event, payload)
    except (HookError, ValueError, OSError) as exc:
        return {"handled": False, "error": str(exc)}


def main() -> None:
    arguments = build_parser().parse_args()
    if arguments.command == "hook":
        print(json.dumps(_run_hook(arguments.event), ensure_ascii=True))
        return

    project_root = Path(__file__).resolve().parents[2]
    installer = GlobalInstaller(project_root, Path(sys.executable))
    if arguments.command in {"install-global", "sync-global"}:
        if arguments.dry_run:
            result = installer.plan()
        else:
            configure_claude = (
                arguments.command == "install-global"
                and not getattr(arguments, "skip_claude_mcp", False)
            )
            result = installer.install(configure_claude_mcp=configure_claude)
    elif arguments.command == "uninstall-global":
        result = installer.uninstall()
    else:
        result = installer.status()
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
