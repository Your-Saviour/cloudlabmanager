Go to [[Introduction]]

## Overview

CloudLabManager includes an MCP (Model Context Protocol) server that allows Claude Code and Claude Desktop to manage cloud instances through natural language. The MCP server runs as a subprocess alongside CLM, communicates via CLM's REST API, and enforces configurable safeguards to prevent runaway costs or accidental destruction.

## Architecture

```
Claude Code/Desktop
  ↕ (stdio or SSE)
MCP Server (Python, FastMCP)
  ↕ (HTTP, JWT auth)
CloudLabManager API (FastAPI)
  ↕ (subprocess)
Ansible → Vultr
```

- The MCP server is a standalone Python process in `app/mcp/`, managed by `MCPProcessManager`
- Config is stored in `AppMetadata` (key `mcp_config`), editable from the CLM UI
- A dedicated `mcp-service` account authenticates to CLM with minimum permissions
- Instance ownership is tracked via `pi-source:mcp` Vultr tags + in-memory tracking
- TTL enforcement rides the existing personal instance cleanup system

## Setup

1. Set `MCP_SERVICE_ACCOUNT_PASSWORD` in your `.env` or `docker-compose.yaml`
2. Rebuild and restart: `docker compose up -d --build`
3. The `mcp-service` user is created automatically on startup
4. Go to the MCP management page in CLM (Admin → MCP Server)
5. Configure allowed services, plan limits, and TTL settings
6. Click **Start** to enable the MCP server

### Claude Code Configuration

Add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "cloudlab": {
      "command": "docker",
      "args": ["compose", "exec", "cloudlabmanager", "python3", "-m", "mcp_server", "--transport", "stdio"]
    }
  }
}
```

For Claude Desktop (SSE transport), the MCP server listens on port 8765 when running.

## Safeguards

| Safeguard | Description |
|-----------|-------------|
| Service allowlist | Only services in `allowed_services` can be created |
| Plan limit | Per-service max plan size, compared by monthly cost |
| Max concurrent | Maximum total active MCP instances (default: 3) |
| Max TTL | Requested TTL clamped to `max_ttl_hours` (default: 8h) |
| Ownership | Can only destroy instances it created (`pi-source:mcp` tag) |
| Script denylist | Cannot run deploy, destroy, snapshot, or reset scripts |

## MCP Tools

| Tool | Description |
|------|-------------|
| `list_available_services` | Show allowed services with defaults and limits |
| `create_instance` | Create a personal VM (enforces all safeguards) |
| `destroy_instance` | Destroy an MCP-created instance (ownership check) |
| `list_instances` | List all MCP-created instances with status |
| `get_connection_info` | Get SSH key, IP, and connection command |
| `extend_ttl` | Reset TTL countdown for an instance |
| `run_script` | Run a service script on an instance (e.g., add-users) |
| `browse_files` | List directory contents on an instance |
| `preview_file` | Preview text file contents on an instance |

## Configuration

Stored in `AppMetadata` under key `mcp_config`:

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `false` | Whether the MCP server process should run |
| `auto_restart` | `true` | Auto-restart on unexpected exit |
| `allowed_services` | `[]` | Services the MCP server can create |
| `max_concurrent` | `3` | Max active MCP instances |
| `default_ttl_hours` | `4` | Default instance TTL |
| `max_ttl_hours` | `8` | Maximum allowed TTL |
| `plan_limits` | `{"default": "vc2-1c-1gb"}` | Max plan per service (by monthly cost) |
| `sse_port` | `8765` | Port for SSE transport |

## Service Account

The `mcp-service` user is seeded on startup with these permissions:

- `personal_instances.create`, `personal_instances.destroy`, `personal_instances.view_all`
- `services.view`, `services.deploy`, `services.plan_select`
- `mcp.config.read`
- `jobs.view_all`, `files.view`

The `pi-source:mcp` tag is injected server-side when the `mcp-service` user creates instances — it cannot be spoofed by regular users.

## Instance Tracking

MCP-created instances are identified by the `pi-source:mcp` Vultr tag. On startup, the MCP server syncs its in-memory tracker from CLM by querying `GET /api/mcp/instances`, which filters inventory objects for this tag. This means tracking survives MCP server restarts.

The existing personal instance TTL cleanup (`personal_instance_cleanup.py`) handles auto-destruction of expired MCP instances — no additional cleanup is needed.

## Management UI

The MCP management page (Admin → MCP Server) has four tabs:

- **Overview** — Process status, start/stop controls, active instance count, Claude config snippet
- **Config** — Edit all settings (allowed services, plan limits, TTL, concurrent limit)
- **Instances** — Table of active MCP instances with force-destroy option
- **Logs** — Auto-refreshing server log viewer

## Logging

MCP server logs are written to `/data/mcp/mcp.log`. Logs auto-rotate at 5MB (keeps one rotated file). View logs from the CLM UI or via `GET /api/mcp/logs`.

## API Endpoints

See [[API Endpoints#MCP Server Management]] for the full endpoint reference.

## Troubleshooting

- **MCP server won't start**: Check that `MCP_SERVICE_ACCOUNT_PASSWORD` is set and the `mcp-service` user exists
- **Instances not tracked after restart**: The tracker syncs from CLM on startup — ensure `GET /api/mcp/instances` returns the expected instances
- **Plan validation fails**: Ensure the plans cache is populated (`GET /api/costs/plans/vc2`) — it refreshes every 6 hours
- **Claude can't connect (stdio)**: Ensure the Docker container is running and the command in the Claude config is correct
- **Claude can't connect (SSE)**: Ensure port 8765 is exposed in `docker-compose.yaml` and the MCP server is running
