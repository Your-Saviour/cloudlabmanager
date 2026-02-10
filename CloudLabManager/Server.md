Go to [[Introduction]]

## Responsibilities

- **Startup**: Load configuration, clone CloudLab repo, create filesystem symlinks, initialize database
- **Authentication**: JWT-based login system with first-boot setup flow
- **Service Discovery**: Scan CloudLab services directory for deployable services
- **Ansible Execution**: Run playbooks asynchronously via subprocess
- **Job Tracking**: Track deployment jobs with live output capture
- **Instance Management**: Cache and serve Vultr inventory data
- **Static File Serving**: Serve the frontend SPA

## Key Modules

| Module | Purpose |
|--------|---------|
| `app.py` | FastAPI app, route registration, CORS, static mount |
| `startup.py` | Startup sequence, symlink creation, DB init |
| `auth.py` | JWT creation/validation, password hashing |
| `ansible_runner.py` | Async Ansible execution, job management |
| `data.py` | JSON database CRUD operations |
| `config.py` | YAML configuration loader |
| `actions.py` | Startup action engine (ENV, CLONE, RUN, RETURN) |
| `dns.py` | Cloudflare API integration |
| `models.py` | Pydantic models for requests/responses |

## Running

```bash
docker compose up -d --build
```

The server starts on port 8000. See [[Architecture]] for the full startup sequence.
