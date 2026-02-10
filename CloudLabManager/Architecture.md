Go to [[Introduction]]

## High-Level Flow

```
Browser --> FastAPI (static files + API) --> Ansible CLI (subprocess) --> Vultr/Cloudflare
                    |
             JSON database (/data/database.json)
```

## Project Structure

```
cloudlabmanager/
├── app/
│   ├── app.py                  # FastAPI entry point, route registration, static mount
│   ├── startup.py              # Startup: clone repos, create symlinks, init DB
│   ├── config.py               # YAML config loader
│   ├── data.py                 # JSON database (read/write/delete)
│   ├── actions.py              # Subprocess + startup action engine
│   ├── dns.py                  # Cloudflare DNS integration
│   ├── auth.py                 # JWT auth, password hashing, user dependency
│   ├── models.py               # Pydantic request/response models
│   ├── ansible_runner.py       # Async ansible execution + job tracking
│   ├── routes/
│   │   ├── auth_routes.py      # /api/auth/* endpoints
│   │   ├── instance_routes.py  # /api/instances/* endpoints
│   │   ├── service_routes.py   # /api/services/* endpoints
│   │   └── job_routes.py       # /api/jobs/* endpoints
│   └── static/
│       ├── index.html          # SPA shell
│       ├── style.css           # Styles
│       └── app.js              # Frontend logic (hash-routed)
├── data/
│   ├── database.json           # Runtime database (gitignored)
│   ├── startup_action.conf.yaml
│   └── key_*                   # SSH keys (gitignored)
├── dockerfile
├── docker-compose.yaml
└── requirements.txt
```

## Startup Sequence

1. FastAPI lifespan calls `startup.main()`
2. Ensures `/data/database.json` exists
3. Loads startup action config from `/data/startup_action.conf.yaml`
4. Loads core settings from `cloudlabsettings/startup.conf.yaml`
5. Clones CloudLab repo to `/app/cloudlab/` (if configured)
6. Creates symlinks so Ansible paths resolve (note: `/vault` is a Docker volume mount, not a symlink — see [[Ansible Integration]]):
   - `/vault` — volume mount from `../cloudlab/vault` (gitignored, not in clone)
   - `/config.yml` -> `/app/cloudlab/config.yml`
   - `/services` -> `/app/cloudlab/services`
   - `/init_playbook` -> `/app/cloudlab/init_playbook`
   - `/scripts` -> `/app/cloudlab/scripts`
   - `/inventory` -> `/app/cloudlab/inventory`
   - `/inputs` -> `/app/cloudlab/inputs`
   - `/outputs` -> `/app/cloudlab/outputs`
7. Initializes database metadata (hostname, DNS zone ID)
8. Writes vault password file if previously configured
9. Creates `AnsibleRunner` instance in app state

## Deployment Job Flow

When a service is deployed, `AnsibleRunner` follows the same pattern as the CloudLab shell scripts:

1. `ansible-playbook start-instances.yaml` — creates Vultr VMs
2. Sleep 15s — wait for SSH readiness
3. `ansible-playbook docker-base/main.yaml` — install Docker on VMs
4. `ansible-playbook services/{name}/main.yaml` — deploy the service

Each step's stdout is captured line-by-line and stored in the Job object. The frontend polls `/api/jobs/{id}` every second to display live output.

## Data Storage

All persistent state is stored in `/data/database.json`:

| Key | Purpose |
|-----|---------|
| `HOST_HOSTNAME` | Container hostname |
| `dns_id` | Cloudflare zone ID |
| `secret_key` | JWT signing key (auto-generated) |
| `users` | User accounts (username -> password_hash) |
| `vault_password` | Ansible vault password |
| `instances_cache` | Cached Vultr inventory data |
| `instances_cache_time` | When inventory was last refreshed |
| `jobs` | Persisted job history |
