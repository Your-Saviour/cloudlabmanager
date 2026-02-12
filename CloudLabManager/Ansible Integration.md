Go to [[Introduction]]

## How It Works

CloudLabManager runs Ansible playbooks using `asyncio.create_subprocess_exec` — the same commands that the CloudLab shell scripts run, but triggered from the web UI instead of a terminal.

## Ansible Runner

The `AnsibleRunner` class (`app/ansible_runner.py`) handles:

- **Service discovery** — scans `cloudlab/services/` for deployable services (those with `deploy.sh`)
- **Deployment** — runs the standard deploy flow via `deploy.sh`
- **Multi-script support** — runs named scripts from `scripts.yaml` with input parameters
- **Stopping** — generates inventory then runs stop-instances
- **Inventory refresh** — runs generate-inventory and caches results
- **Job tracking** — each operation creates a Job with unique ID, persisted to SQLite
- **Config management** — read/write service config files (instance.yaml, config.yaml, scripts.yaml)
- **File management** — list, upload, download, edit, delete files in service inputs/outputs directories
- **SSH credential resolution** — scans service inventory files to find SSH keys for hostnames
- **Inventory actions** — execute configurable actions on inventory objects (scripts, playbooks, SSH)

## Deployment Steps

Mirrors the CloudLab deploy scripts (e.g., `services/n8n-server/deploy.sh`):

```
1. ansible-playbook /init_playbook/start-instances.yaml \
     --vault-password-file /tmp/.vault_pass.txt \
     -e instances_file=/services/{name}/instance.yaml

2. sleep 15  (wait for SSH readiness)

3. ansible-playbook /services/docker-base/main.yaml \
     -i /services/{name}/outputs/temp_inventory.yaml

4. ansible-playbook /services/{name}/main.yaml \
     -i /services/{name}/outputs/temp_inventory.yaml
```

## Multi-Script Support

Services can define multiple runnable scripts in a `scripts.yaml` file:

```yaml
scripts:
  - name: deploy
    label: Deploy
    script: deploy.sh
  - name: add-user
    label: Add User
    script: add-user.sh
    inputs:
      - name: username
        label: Username
        type: string
        required: true
```

Scripts are executed via `POST /api/services/{name}/run` with a JSON body specifying the script name and inputs. Input values are passed as environment variables to the script (e.g., `INPUT_USERNAME`).

## Service Discovery

A directory under `cloudlab/services/` is a deployable service if it contains:
- `deploy.sh` — deployment script
- Optionally `instance.yaml` — Vultr VM definition (plan, region, OS, tags)
- Optionally `main.yaml` — Ansible playbook entry point
- Optionally `scripts.yaml` — multi-script definitions with inputs

The instance.yaml is parsed and shown in the UI so you can see what VMs will be created before deploying.

## Persistent Storage

Service deployment outputs (temp inventories, generated files) are preserved across container rebuilds in `/data/persistent/services/{name}/outputs/`. On startup, these are symlinked back into the cloned repo so subsequent playbook runs can access previous outputs.

Similarly, `/data/persistent/inputs/` preserves uploaded input files and `/data/persistent/inventory/` preserves inventory data.

## Symlinks & Volume Mounts

After the CloudLab repo is cloned to `/app/cloudlab/`, symlinks are created at the root filesystem level so that hardcoded paths in playbooks resolve correctly:

| Path | Source | Notes |
|------|--------|-------|
| `/vault` | Volume mount (`../cloudlab/vault:/vault:ro`) | Mounted directly because `vault/` is gitignored and not present after clone |
| `/config.yml` | Symlink → `/app/cloudlab/config.yml` | |
| `/services` | Symlink → `/app/cloudlab/services` | |
| `/init_playbook` | Symlink → `/app/cloudlab/init_playbook` | |
| `/scripts` | Symlink → `/app/cloudlab/scripts` | |
| `/inventory` | Symlink → `/app/cloudlab/inventory` | Created by startup (`os.makedirs`) |
| `/inputs` | Symlink → `/app/cloudlab/inputs` | Gitignored, may not exist |
| `/outputs` | Symlink → `/app/cloudlab/outputs` | Gitignored, may not exist |
| `/instance_templates` | Symlink → `/app/cloudlab/instance_templates` | |
| `/inventory_types` | Symlink → `/app/cloudlab/inventory_types` | Type definitions for inventory system |

## Docker Image

The Dockerfile installs:
- `openssh-client` and `sshpass` — for Ansible SSH connectivity
- `ansible` — via pip in the Python venv
- Ansible collections: `vultr.cloud`, `community.general`, `community.docker`, `community.crypto`
