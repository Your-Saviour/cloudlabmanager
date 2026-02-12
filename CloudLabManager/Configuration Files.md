Go to [[Introduction]]

## Docker Compose Environment Variables

Set in `docker-compose.yaml` or `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `HOST_HOSTNAME` | Yes | Hostname identifier for this instance |
| `CLOUDFLARE_API_TOKEN` | Yes | Cloudflare API token for DNS zone verification |
| `VAULT_PASSWORD` | No | Ansible vault password (alternative to entering via UI) |
| `LOCAL_MODE` | No | Set to `true` to skip Cloudflare DNS validation |
| `SENDAMATIC_API_KEY` | No | Sendamatic email API key (for user invitations and password resets) |
| `SENDAMATIC_SENDER_EMAIL` | No | Sender email address for outgoing emails |
| `SENDAMATIC_SENDER_NAME` | No | Sender display name (default: "CloudLab Manager") |
| `ALLOWED_ORIGINS` | No | CORS allowed origins (default: `*`) |

## Startup Configuration

### `/data/startup_action.conf.yaml`

Controls what happens when the container starts. Supports commands:
- `ENV key=value` — set an environment variable
- `CLONE git_url` — clone a git repository
- `RUN command` — execute a shell command
- `RETURN path` — return a path to use as the settings file

Currently configured to return the path to `cloudlabsettings/startup.conf.yaml`.

### `cloudlabsettings/startup.conf.yaml`

Loaded by the startup sequence. Contains:
- `core_settings` — path to the core settings file
- `git_url` — CloudLab repo URL to clone
- `git_key` — SSH key path for git authentication

### Core Settings (from cloudlabsettings)

- `dns_basename` — domain name to verify in Cloudflare

## Database

All runtime state is stored in SQLite at `/data/cloudlab.db` using SQLAlchemy ORM with WAL mode.

The database is initialized automatically on first boot. If a legacy `database.json` exists, it is migrated to SQLite automatically. See [[Architecture#Data Storage]] for the full table reference.

Key data stored in the `app_metadata` key-value table:
- `secret_key` — JWT signing key (auto-generated)
- `vault_password` — Ansible vault password
- `HOST_HOSTNAME` — Container hostname
- `dns_id` — Cloudflare zone ID
- `instances_cache` — Cached Vultr inventory data
- `instances_cache_time` — When inventory was last refreshed

## Persistent Storage

The `/data/persistent/` directory preserves data across container rebuilds:

| Path | Purpose |
|------|---------|
| `persistent/services/{name}/outputs/` | Service deployment outputs (temp inventories, generated files) |
| `persistent/inventory/` | Inventory data files |
| `persistent/inputs/` | Uploaded input files for services |

On startup, persistent data is symlinked back into the cloned CloudLab repo so playbooks can access previous deployment outputs.

## Volumes

| Mount | Purpose |
|-------|---------|
| `./data:/data` | Persistent storage (SQLite database, SSH keys, startup config, persistent data) |
| `../cloudlabsettings:/app/cloudlabsettings` | Settings repository |
| `../cloudlab/vault:/vault:ro` | Ansible vault secrets (read-only). Mounted directly at `/vault` because `vault/` is gitignored and not available after cloning the CloudLab repo. |
