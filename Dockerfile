#!BuildTag: mcp-agama:%VERSION%
#!UseOBSRepositories

FROM registry.opensuse.org/opensuse/bci/python:3.13

RUN zypper --non-interactive in python313-uv

# Non-root user — mirrors mcp-bugzilla's security practice
RUN useradd -m -u 1001 -d /home/agama agama

COPY . /home/agama/app/

RUN chown -R agama:agama /home/agama/app

WORKDIR /home/agama/app

USER 1001

RUN uv sync --locked

# ── Environment variables (all overridable at runtime) ──────────────────────
# URL of the Agama HTTP API (live ISO: http://localhost/api)
ENV AGAMA_SERVER="http://localhost/api"

# Root password for PAM authentication (empty = no auth on fresh live ISO)
ENV AGAMA_PASSWORD=""

# Pre-fetched JWT token (skips password auth if set)
ENV AGAMA_TOKEN=""

# MCP server listen address
ENV MCP_HOST="0.0.0.0"
ENV MCP_PORT="8000"
ENV MCP_TRANSPORT="http"

# Set to "true" to disable all write tools (safe exploration mode)
ENV MCP_READ_ONLY="false"

# Comma-separated tool names to selectively disable
# Example: MCP_AGAMA_DISABLED_METHODS=agama_run_action,agama_set_config
ENV MCP_AGAMA_DISABLED_METHODS=""

ENV LOG_LEVEL="INFO"

EXPOSE 8000

ENTRYPOINT ["uv", "run", "mcp-agama"]
