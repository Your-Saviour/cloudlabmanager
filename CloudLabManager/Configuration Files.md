Go to [[Introduction]]

## Docker Compose Environment Variables

Set in `docker-compose.yaml`:

| Variable | Required | Description |
|----------|----------|-------------|
| `HOST_HOSTNAME` | Yes | Hostname identifier for this instance |
| `CLOUDFLARE_API_TOKEN` | Yes | Cloudflare API token for DNS zone verification |
| `VAULT_PASSWORD` | No | Ansible vault password (alternative to entering via UI) |

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

- `database_location` — path to database.json
- `dns_basename` — domain name to verify in Cloudflare

## Runtime Database

`/data/database.json` stores all runtime state. See [[Architecture]] for the full key reference.

## Volumes

| Mount | Purpose |
|-------|---------|
| `./data:/data` | Persistent storage (database, SSH keys, startup config) |
| `../cloudlabsettings:/app/cloudlabsettings` | Settings repository |
| `../cloudlab/vault:/vault:ro` | Ansible vault secrets (read-only). Mounted directly at `/vault` because `vault/` is gitignored and not available after cloning the CloudLab repo. |
