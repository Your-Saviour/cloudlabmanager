Go to [[Introduction]]

## How It Works

CloudLabManager runs Ansible playbooks using `asyncio.create_subprocess_exec` — the same commands that the CloudLab shell scripts run, but triggered from the web UI instead of a terminal.

## Ansible Runner

The `AnsibleRunner` class (`app/ansible_runner.py`) handles:

- **Service discovery** — scans `cloudlab/services/` for deployable services
- **Deployment** — runs the standard 3-step deploy flow
- **Stopping** — generates inventory then runs stop-instances
- **Inventory refresh** — runs generate-inventory and caches results
- **Job tracking** — each operation creates a Job with unique ID

## Deployment Steps

Mirrors the CloudLab shell scripts (e.g., `scripts/n8n-server.sh`):

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

## Service Discovery

A directory under `cloudlab/services/` is a deployable service if it contains:
- `instance.yaml` — Vultr VM definition (plan, region, OS, tags)
- `main.yaml` — Ansible playbook entry point

The instance.yaml is parsed and shown in the UI so you can see what VMs will be created before deploying.

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

## Docker Image

The Dockerfile installs:
- `openssh-client` and `sshpass` — for Ansible SSH connectivity
- `ansible` — via pip in the Python venv
- Ansible collections: `vultr.cloud`, `community.general`, `community.docker`, `community.crypto`
