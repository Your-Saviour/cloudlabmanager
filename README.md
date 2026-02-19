# CloudLab Manager

Web-based management interface for [CloudLab](../cloudlab) infrastructure. Deploy services, manage Vultr instances, and run Ansible playbooks from the browser.

## Quick Start

```bash
docker compose up -d --build
# Open http://localhost:8000
```

On first boot, create an admin account and enter the Ansible vault password. Then log in to access the dashboard.

## Features

- **Service Discovery** — automatically detects deployable services from the CloudLab repo
- **One-Click Deploy** — deploy any service with a single button click
- **Multi-Script Support** — services can define multiple runnable scripts with input parameters
- **Live Output** — watch Ansible playbook output in real-time via WebSocket
- **Instance Management** — view and refresh Vultr instance inventory
- **Job Tracking** — full history of all deployment and management jobs
- **RBAC** — role-based access control with customizable roles and granular permissions
- **User Management** — invite users via email, manage roles, password resets
- **Inventory System** — type-driven infrastructure tracking with tags, ACLs, and sync adapters
- **WebSocket SSH** — browser-based SSH terminals to managed servers
- **Audit Logging** — full trail of all user actions with timestamps and IP addresses
- **Email Notifications** — invitation, password reset, and alert emails via SMTP or Sendamatic (auto-selects transport based on configuration)
- **Config & File Management** — edit service configs and manage input/output files from the UI
- **Bulk Operations** — multi-select services or inventory items for batch stop, deploy, delete, tag, and custom actions
- **Credential Access Control** — restrict which roles see which credential types per instance, with personal SSH key support and audit logging
- **Persistent Storage** — deployment outputs survive container rebuilds

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CLOUDFLARE_API_TOKEN` | Yes | Cloudflare API token |
| `HOST_HOSTNAME` | Yes | Hostname identifier |
| `VAULT_PASSWORD` | No | Ansible vault password (alternative to UI entry) |
| `LOCAL_MODE` | No | Skip Cloudflare DNS validation (`true`/`false`) |
| `SENDAMATIC_API_KEY` | No | Sendamatic email API key |
| `SENDAMATIC_SENDER_EMAIL` | No | Sender email address |
| `SENDAMATIC_SENDER_NAME` | No | Sender display name (default: "CloudLab Manager") |
| `SMTP_HOST` | No | SMTP server hostname (enables SMTP transport when set) |
| `SMTP_PORT` | No | SMTP server port (default: 587) |
| `SMTP_USERNAME` | No | SMTP authentication username |
| `SMTP_PASSWORD` | No | SMTP authentication password |
| `SMTP_USE_TLS` | No | Enable STARTTLS (default: true) |
| `SMTP_SENDER_EMAIL` | No | SMTP sender email (falls back to Sendamatic sender) |
| `SMTP_SENDER_NAME` | No | SMTP sender display name (default: "CloudLab Manager") |
| `ALLOWED_ORIGINS` | No | CORS allowed origins (default: `*`) |

## Password Reset

If you forget your password, reset it from the CLI:

```bash
# Interactive — prompts for user selection and new password
docker compose exec cloudlabmanager python3 /app/reset_password.py

# Specify the username directly
docker compose exec cloudlabmanager python3 /app/reset_password.py --username jake
```

## Testing

```bash
# Unit + integration tests
docker compose exec cloudlabmanager pytest tests/unit tests/integration

# Playwright browser tests
docker compose exec cloudlabmanager pytest tests/playwright -v

# E2E tests (real Vultr — costs money)
docker compose exec cloudlabmanager pytest tests/e2e -m e2e -v
```

## Documentation

Full documentation is in the `CloudLabManager/` directory (Obsidian vault). Start with [Introduction](CloudLabManager/Introduction.md).
