"""
agama-mcp — MCP server for the Agama installer.
Entrypoint: mcp-agama (defined in pyproject.toml [project.scripts])

CLI/env-var priority (mirrors mcp-bugzilla):
  CLI argument  >  environment variable  >  hardcoded default
"""

import argparse
import os
import sys

from . import server
from .agama_client import mcp_log


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mcp-agama",
        description="MCP server for the Agama openSUSE/SUSE installer.",
    )

    # ── Connection ─────────────────────────────────────────────────────────
    parser.add_argument(
        "--agama-server",
        type=str,
        default=os.getenv("AGAMA_SERVER", "http://localhost/api"),
        help=(
            "Base URL of the Agama HTTP API. "
            "Defaults to http://localhost/api or AGAMA_SERVER env var. "
            "On the live ISO this is the local address; from a dev machine "
            "point it at your VM, e.g. http://192.168.122.100/api"
        ),
    )

    # ── Authentication ─────────────────────────────────────────────────────
    parser.add_argument(
        "--password",
        type=str,
        default=os.getenv("AGAMA_PASSWORD", ""),
        help=(
            "Root password of the Agama live ISO for initial authentication. "
            "Empty string on a fresh boot (no password set). "
            "Uses AGAMA_PASSWORD env var if not provided."
        ),
    )
    parser.add_argument(
        "--token",
        type=str,
        default=os.getenv("AGAMA_TOKEN", ""),
        help=(
            "Pre-fetched JWT bearer token. Skips password authentication. "
            "Uses AGAMA_TOKEN env var if not provided."
        ),
    )

    # ── MCP server network ────────────────────────────────────────────────
    parser.add_argument(
        "--host",
        type=str,
        default=os.getenv("MCP_HOST", "127.0.0.1"),
        help="Host address for the MCP server to listen on. Default: 127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8000")),
        help="Port for the MCP server to listen on. Default: 8000",
    )
    parser.add_argument(
        "--transport",
        type=str,
        choices=["http", "stdio"],
        default=os.getenv("MCP_TRANSPORT", "http"),
        help=(
            "MCP transport mode. "
            "'http' for mcphost / Claude Desktop over SSE. "
            "'stdio' for direct pipe mode. "
            "Default: http"
        ),
    )

    # ── Safety flags ──────────────────────────────────────────────────────
    parser.add_argument(
        "--read-only",
        action="store_true",
        default=os.getenv("MCP_READ_ONLY", "false").lower() == "true",
        help=(
            "Disables all tools that modify installer state "
            "(agama_set_config, agama_run_action). "
            "Safe mode for exploration and documentation. "
            "Can also be set via MCP_READ_ONLY=true."
        ),
    )

    args = parser.parse_args()

    if not args.agama_server:
        mcp_log.critical(
            "Error: --agama-server or AGAMA_SERVER env var must be set. Exiting."
        )
        sys.exit(1)

    # Pass parsed args to the server module (mirrors mcp-bugzilla's pattern)
    server.cli_args = args
    server.start()


if __name__ == "__main__":
    main()

