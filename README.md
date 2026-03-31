# mcp-agama

MCP server for the **Agama openSUSE/SUSE installer** — the AI onboarding
assistant layer for **openSUSE Leap 16**.

Modeled directly on **[openSUSE/mcp-bugzilla](https://github.com/openSUSE/mcp-bugzilla)**:
same FastMCP pattern, same `uv` toolchain, same Podman/Docker setup, same
selective tool-disable via env vars.

```
mcphost (mark3labs/mcphost — the runtime host)
      │  loads config, runs LLM, handles tool-calling loop
      ▼
  mcp-agama  
      ├── agama_status()          GET  /api/v2/status
      ├── agama_system()          GET  /api/v2/system
      ├── agama_config()          GET  /api/v2/config
      ├── agama_extended_config() GET  /api/v2/extended_config
      ├── agama_proposal()        GET  /api/v2/proposal
      ├── agama_issues()          GET  /api/v2/issues
      ├── agama_questions()       GET  /api/v2/questions
      ├── agama_set_config()  [write] PATCH /api/v2/config
      ├── agama_run_action()  [write] POST  /api/v2/action
      └── system_state()          /proc + /etc/os-release
```

---

## Quick start

### 1. Install uv (if not already)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# or on openSUSE:
zypper in python313-uv
```

### 2. Install dependencies
```bash
cd agama-mcp
uv sync
```

### 3. Boot Agama live ISO in a VM
```bash
# QEMU with port forwarding (port 8080 → VM port 80)
qemu-system-x86_64 \
  -m 4G -smp 2 \
  -cdrom agama-installer-leap16.iso \
  -net user,hostfwd=tcp::8080-:80 \
  -net nic \
  -hda /tmp/test-disk.qcow2

# Download ISO from:
# https://download.opensuse.org/distribution/leap/16.0/
```

### 4. Run the server
```bash
# HTTP transport (for mcphost / Claude Desktop)
uv run mcp-agama --agama-server http://localhost:8080/api --password ""

# Read-only mode (safe for exploration)
uv run mcp-agama --agama-server http://localhost:8080/api --read-only

# stdio transport (for direct pipe / Claude Desktop stdio mode)
uv run mcp-agama --agama-server http://localhost:8080/api --transport stdio
```

### 5. Wire up mcphost
```bash
# Install mcphost
go install github.com/mark3labs/mcphost@latest

# Run with your local Ollama or other LLM
mcphost --config config.yaml --model ollama:llama3.1
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `AGAMA_SERVER` | `http://localhost/api` | Agama API base URL |
| `AGAMA_PASSWORD` | `` | Root password (empty on fresh live ISO) |
| `AGAMA_TOKEN` | `` | Pre-fetched JWT (skips password auth) |
| `MCP_HOST` | `127.0.0.1` | MCP server listen host |
| `MCP_PORT` | `8000` | MCP server listen port |
| `MCP_TRANSPORT` | `http` | `http` or `stdio` |
| `MCP_READ_ONLY` | `false` | Disable all write tools |
| `MCP_AGAMA_DISABLED_METHODS` | `` | Comma-separated tools to disable |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## Running with Podman (mirrors mcp-bugzilla)

```bash
# Build
podman build -t mcp-agama .

# Run (pointing at a VM on your network)
podman run --rm -p 8000:8000 \
  -e AGAMA_SERVER=http://192.168.122.100/api \
  -e AGAMA_PASSWORD=linux \
  mcp-agama

# Read-only / safe exploration
podman run --rm -p 8000:8000 \
  -e AGAMA_SERVER=http://192.168.122.100/api \
  -e MCP_READ_ONLY=true \
  mcp-agama

# Disable specific tools
podman run --rm -p 8000:8000 \
  -e AGAMA_SERVER=http://192.168.122.100/api \
  -e MCP_AGAMA_DISABLED_METHODS=agama_run_action \
  mcp-agama
```

---

## Running tests

```bash
uv run pytest
```

---

## Agama API surface (from source — `agama-server/src/server/web.rs`)

| Method | Path | Tool |
|---|---|---|
| POST | `/api/auth` | (startup auth) |
| GET | `/api/v2/status` | `agama_status()` |
| GET | `/api/v2/system` | `agama_system()` |
| GET | `/api/v2/config` | `agama_config()` |
| GET | `/api/v2/extended_config` | `agama_extended_config()` |
| GET | `/api/v2/proposal` | `agama_proposal()` |
| GET | `/api/v2/issues` | `agama_issues()` |
| GET/POST/PATCH | `/api/v2/questions` | `agama_questions()` |
| PATCH | `/api/v2/config` | `agama_set_config()` [write] |
| POST | `/api/v2/action` | `agama_run_action()` [write] |

---

## Contribution ideas

- **`query_docs()` tool**: vector store (Qdrant/ChromaDB or even OpenViking) fed by `agama_system()`
  output — lets the AI answer "what disks do I have?" from cached context.
- **WebSocket events tool**: Agama emits real-time progress via `/api/ws` —
  a streaming `agama_events()` tool would eliminate polling.
- **`explain_command()` tool**: wraps `man zypper`, `zypper help`, `agama --help`
  for the AI to explain CLI usage in context.
