"""
MCP server for the Agama installer — AI onboarding assistant for openSUSE Leap 16.

Architecture mirrors openSUSE/mcp-bugzilla:
  FastMCP instance → @mcp.tool() decorators → AgamaClient HTTP layer
  Write tools tagged with tags={"write"} → disabled by --read-only flag
  Selective disable via MCP_AGAMA_DISABLED_METHODS env var

Tool map (mirrors mcp-bugzilla's bug_info / bug_comments / bugs_quicksearch pattern):
  agama_status()          → GET  /api/v2/status
  agama_system()          → GET  /api/v2/system
  agama_config()          → GET  /api/v2/config
  agama_extended_config() → GET  /api/v2/extended_config
  agama_proposal()        → GET  /api/v2/proposal
  agama_issues()          → GET  /api/v2/issues
  agama_questions()       → GET  /api/v2/questions
  agama_set_config()      → PATCH /api/v2/config          [write]
  agama_run_action()      → POST  /api/v2/action           [write]
  system_state()          → /proc + /etc/os-release (local read)
"""

import json
import platform
import subprocess
from argparse import Namespace
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .agama_client import AgamaClient, mcp_log


# ── FastMCP instance (name shown in mcphost UI) ───────────────────────────────
mcp = FastMCP("agama-installer")

# Populated by main() in __init__.py before start() is called
cli_args: Namespace

# Shared client — created once in start(), reused across all tool calls
_client: AgamaClient


# ── Tool definitions ──────────────────────────────────────────────────────────


@mcp.tool()
async def agama_status() -> dict[str, Any]:
    """
    Returns the current installation stage and active progress indicators.

    Stage values:
      configuring — safe to change settings
      installing  — DO NOT reboot or power off
      finished    — installation complete, safe to reboot
      failed      — check issues and logs

    Use this as the primary heartbeat signal for the onboarding AI.
    Call it before every other tool to understand installer state.
    """

    mcp_log.info("[LLM-REQ] agama_status()")
    try:
        data = await _client.get_status()
        stage = data.get("stage", "unknown")
        stage_notes = {
            "configuring": "Safe to change settings.",
            "installing": "Installation in progress — do NOT reboot.",
            "finished": "Installation complete — safe to reboot.",
            "failed": "Installation failed — check agama_issues() and logs.",
        }
        data["_note"] = stage_notes.get(stage, "Unknown stage.")
        mcp_log.info(f"[LLM-RES] stage={stage}")
        return data
    except Exception as e:
        raise ToolError(f"Failed to get installer status\nReason: {e}")


@mcp.tool()
async def agama_system() -> dict[str, Any]:
    """
    Returns the full system snapshot: detected storage devices, network connections,
    available locales, keyboard layouts, timezones, and hardware details.

    This is the richest single context signal for the RAG pipeline.
    Feed it into your vector store to answer questions like:
      "What disks do I have?"
      "What network interfaces are available?"
      "What timezones are available for my region?"
    """

    mcp_log.info("[LLM-REQ] agama_system()")
    try:
        data = await _client.get_system()
        mcp_log.info("[LLM-RES] system snapshot retrieved")
        return data
    except Exception as e:
        raise ToolError(f"Failed to get system info\nReason: {e}")


@mcp.tool()
async def agama_config() -> dict[str, Any]:
    """
    Returns only the configuration that the user has explicitly set so far.

    Missing keys mean 'not yet configured'. Use agama_extended_config() to see
    the full merged view including defaults. Useful for the AI to understand
    what the user has intentionally chosen vs what is still at default.
    """

    mcp_log.info("[LLM-REQ] agama_config()")
    try:
        data = await _client.get_config()
        mcp_log.info("[LLM-RES] config retrieved")
        return data
    except Exception as e:
        raise ToolError(f"Failed to get config\nReason: {e}")


@mcp.tool()
async def agama_extended_config() -> dict[str, Any]:
    """
    Returns the merged configuration: user config + defaults from system and product info.

    This is what Agama actually uses to compute the installation proposal.
    Useful for showing the user the complete picture of what will happen
    if they proceed without changing anything.
    """

    mcp_log.info("[LLM-REQ] agama_extended_config()")
    try:
        data = await _client.get_extended_config()
        mcp_log.info("[LLM-RES] extended config retrieved")
        return data
    except Exception as e:
        raise ToolError(f"Failed to get extended config\nReason: {e}")


@mcp.tool()
async def agama_proposal() -> dict[str, Any]:
    """
    Returns the installation proposal — the concrete plan for what will be written
    to disk, which packages will be installed, and how the system will be configured.

    Returns a _no_proposal flag if no proposal has been calculated yet (storage and
    product must be configured first). The AI should explain this in plain language
    to help users understand partitioning and package selection decisions.
    """

    mcp_log.info("[LLM-REQ] agama_proposal()")
    try:
        data = await _client.get_proposal()
        mcp_log.info("[LLM-RES] proposal retrieved")
        return data
    except Exception as e:
        # 404 = no proposal yet, not a hard error
        if "404" in str(e) or "Not Found" in str(e):
            mcp_log.info("[LLM-RES] no proposal yet")
            return {
                "_no_proposal": True,
                "_note": "No proposal calculated yet. Configure storage and product selection first.",
            }
        raise ToolError(f"Failed to get proposal\nReason: {e}")


@mcp.tool()
async def agama_issues() -> dict[str, Any]:
    """
    Returns the list of validation issues that would block installation.

    Each issue has:
      scope       — which subsystem raised it (storage/software/network/users/…)
      description — human-readable explanation
      severity    — error or warning

    The AI onboarding assistant should surface blocking issues prominently and
    guide the user to fix them before triggering agama_run_action("install").
    Returns blocking_install=True if there are any issues.
    """

    mcp_log.info("[LLM-REQ] agama_issues()")
    try:
        issues = await _client.get_issues()
        mcp_log.info(f"[LLM-RES] {len(issues)} issues found")
        return {
            "count": len(issues),
            "blocking_install": len(issues) > 0,
            "issues": issues,
            "_note": (
                "Fix all issues before triggering 'install' action."
                if issues
                else "No issues — installer is ready."
            ),
        }
    except Exception as e:
        raise ToolError(f"Failed to get issues\nReason: {e}")


@mcp.tool()
async def agama_questions() -> dict[str, Any]:
    """
    Returns any pending questions from the Agama backend that require user input.

    Examples: encryption password prompts, LUKS confirmation, unknown disk warnings.
    The AI should relay these conversationally and answer them using
    agama_set_config() or a direct PATCH /questions call.
    """

    mcp_log.info("[LLM-REQ] agama_questions()")
    try:
        questions = await _client.get_questions()
        mcp_log.info(f"[LLM-RES] {len(questions)} pending questions")
        return {
            "pending_count": len(questions),
            "questions": questions,
            "_note": (
                "These require user answers before installation can proceed."
                if questions
                else "No pending questions."
            ),
        }
    except Exception as e:
        raise ToolError(f"Failed to get questions\nReason: {e}")


@mcp.tool(tags={"write"})
async def agama_set_config(update: dict[str, Any]) -> dict[str, Any]:
    """
    Applies a partial configuration update via PATCH /api/v2/config.

    The update dict is merged into the current extended config. Only the keys
    you provide are changed — everything else stays as-is. This is the safe
    way to apply user choices conversationally.
    """

    mcp_log.info(f"[LLM-REQ] agama_set_config(keys={list(update.keys())})")
    try:
        result = await _client.patch_config(update)
        mcp_log.info("[LLM-RES] config patched")
        return result or {"status": "ok", "patched_keys": list(update.keys())}
    except Exception as e:
        raise ToolError(f"Failed to patch config\nReason: {e}")


@mcp.tool(tags={"write"})
async def agama_run_action(action: Any) -> dict[str, Any]:
    """
    Triggers a one-shot action on the Agama backend.

    WARNING: "install" is DESTRUCTIVE and IRREVERSIBLE.
    """

    mcp_log.info(f"[LLM-REQ] agama_run_action(action={str(action)[:60]})")
    try:
        result = await _client.run_action(action)
        mcp_log.info("[LLM-RES] action completed")
        return result or {"status": "ok", "action": action}
    except Exception as e:
        msg = str(e)
        if "422" in msg or "Unprocessable" in msg:
            raise ToolError(
                f"Action blocked (422): installer has pending issues or is busy. "
                f"Call agama_issues() to see what needs fixing first.\nDetail: {msg}"
            )
        raise ToolError(f"Failed to run action '{action}'\nReason: {msg}")


@mcp.tool()
async def system_state() -> dict[str, Any]:
    """
    Reads the local machine's OS identity and hardware summary directly from
    /etc/os-release, /proc/cpuinfo, /proc/meminfo, and lsblk.

    Useful when the MCP server runs inside the live ISO itself.
    """

    mcp_log.info("[LLM-REQ] system_state()")

    state: dict[str, Any] = {}

    # /etc/os-release
    os_release = Path("/etc/os-release")
    if os_release.exists():
        parsed: dict[str, str] = {}
        for line in os_release.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                parsed[k.strip()] = v.strip().strip('"')
        state["os"] = {
            "name": parsed.get("NAME", "unknown"),
            "version": parsed.get("VERSION", parsed.get("VERSION_ID", "unknown")),
            "id": parsed.get("ID", "unknown"),
            "pretty_name": parsed.get("PRETTY_NAME", "unknown"),
        }
    else:
        state["os"] = {"name": platform.system(), "version": platform.release()}

    state["arch"] = platform.machine()

    # /proc/cpuinfo
    cpu_info = Path("/proc/cpuinfo")
    if cpu_info.exists():
        text = cpu_info.read_text()
        models = [l.split(":")[1].strip() for l in text.splitlines() if "model name" in l]
        state["cpu"] = {
            "model": models[0] if models else "unknown",
            "cores": len([l for l in text.splitlines() if l.startswith("processor")]),
        }

    # /proc/meminfo
    mem_info = Path("/proc/meminfo")
    if mem_info.exists():
        for line in mem_info.read_text().splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                state["ram_gb"] = round(kb / 1024 / 1024, 1)
                break

    # lsblk
    try:
        lsblk = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if lsblk.returncode == 0:
            state["block_devices"] = json.loads(lsblk.stdout)
        else:
            state["block_devices"] = "lsblk returned non-zero"
    except FileNotFoundError:
        state["block_devices"] = "lsblk not available"
    except Exception as ex:
        state["block_devices"] = f"error: {ex}"

    mcp_log.info(
        f"[LLM-RES] system_state: os={state.get('os', {}).get('pretty_name','?')}"
    )
    return state


# ── Selective disable (mirrors mcp-bugzilla's disable_components_selectively) ──
def disable_components_selectively() -> None:
    """
    Disables MCP tools listed in MCP_AGAMA_DISABLED_METHODS (comma-separated).
    Example: MCP_AGAMA_DISABLED_METHODS=agama_run_action,agama_set_config
    """

    import os

    disabled_list = [
        d.strip().upper()
        for d in os.getenv("MCP_AGAMA_DISABLED_METHODS", "").split(",")
        if d.strip()
    ]
    if not disabled_list:
        return

    for key, component in mcp.local_provider._components.items():
        name = getattr(component, "name", None)
        if name and name.upper() in disabled_list:
            mcp_log.info(f"Disabling tool '{name}' via MCP_AGAMA_DISABLED_METHODS")
            mcp.disable(keys={key})


def disable_write_tools() -> None:
    """Disables all write-tagged tools when --read-only flag is set."""

    read_only = getattr(cli_args, "read_only", False)
    if read_only:
        mcp_log.info("Read-only mode: disabling all write-tagged tools")
        mcp.disable(tags={"write"})


# ── Server startup ─────────────────────────────────────────────────────────────
def start() -> None:
    """
    Initialises the AgamaClient, optionally authenticates, then runs FastMCP.
    Called by __init__.main() after CLI args are parsed.
    """

    global _client

    base_url = cli_args.agama_server
    password = getattr(cli_args, "password", "")
    token = getattr(cli_args, "token", "")

    _client = AgamaClient(base_url=base_url, token=token)

    # If a password was provided and no token, authenticate at startup
    if password and not token:
        import asyncio

        try:
            tok = asyncio.get_event_loop().run_until_complete(
                _client.authenticate(password)
            )
            mcp_log.info(f"Authenticated with Agama at {base_url} (token: {tok[:16]}…)")
        except Exception as e:
            mcp_log.warning(
                f"Authentication failed: {e}\n"
                "Continuing without token — unauthenticated endpoints may work on fresh live ISO."
            )

    disable_components_selectively()
    disable_write_tools()

    transport = getattr(cli_args, "transport", "http")
    host = getattr(cli_args, "host", "127.0.0.1")
    port = getattr(cli_args, "port", 8000)

    mcp_log.info(
        f"Starting agama-mcp on {host}:{port} (transport={transport}) "
        f"→ Agama at {base_url}"
    )
    mcp.run(transport=transport, host=host, port=port, show_banner=False)

