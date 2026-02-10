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
- **Live Output** — watch Ansible playbook output in real-time
- **Instance Management** — view and refresh Vultr instance inventory
- **Job Tracking** — full history of all deployment and management jobs
- **JWT Authentication** — secure access with first-boot setup flow

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CLOUDFLARE_API_TOKEN` | Yes | Cloudflare API token |
| `HOST_HOSTNAME` | Yes | Hostname identifier |
| `VAULT_PASSWORD` | No | Ansible vault password (alternative to UI entry) |

## Password Reset

If you forget your password, reset it from the CLI:

```bash
# Interactive — prompts for user selection and new password
docker compose exec cloudlabmanager python3 /app/reset_password.py

# Specify the username directly
docker compose exec cloudlabmanager python3 /app/reset_password.py --username jake
```

## Documentation

Full documentation is in the `CloudLabManager/` directory (Obsidian vault). Start with [Introduction](CloudLabManager/Introduction.md).
