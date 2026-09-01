from __future__ import annotations

import argparse

from universal_agent_control_plane.api import main as http_main
from universal_agent_control_plane.server import main as stdio_main


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Universal Agent Control Plane")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run the combined Streamable HTTP MCP and REST gateway",
    )
    arguments, remaining = parser.parse_known_args()
    if arguments.http:
        import sys

        sys.argv = [sys.argv[0], *remaining]
        http_main()
    elif remaining:
        parser.error(f"unrecognized arguments: {' '.join(remaining)}")
    else:
        stdio_main()


if __name__ == "__main__":
    main()
