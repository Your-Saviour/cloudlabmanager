Go to [[Introduction]]

## Overview

CloudLabManager uses JWT (JSON Web Tokens) for authentication. Tokens are issued on login and expire after 24 hours.

## First-Time Setup

On first boot, no users exist. The frontend detects this via `GET /api/auth/status` and shows the Setup page. Setup creates the initial admin account and sets the Ansible vault password in one step.

After setup, the `/api/auth/setup` endpoint is permanently disabled.

## Login Flow

1. User submits username + password to `POST /api/auth/login`
2. Server verifies password against bcrypt hash stored in `database.json`
3. Server returns a JWT signed with a secret key (auto-generated on first boot)
4. Frontend stores the token in `localStorage`
5. All subsequent API requests include `Authorization: Bearer <token>`

## Implementation Details

- **JWT library**: python-jose
- **Password hashing**: passlib with bcrypt (pinned to bcrypt < 4.1 for compatibility)
- **Secret key**: 32-byte hex token, generated once and stored in `database.json`
- **Token expiry**: 24 hours
- **Protected routes**: Use `Depends(get_current_user)` FastAPI dependency

## Vault Password

The Ansible vault password is needed to decrypt `secrets.yml` in the CloudLab repo. It can be set in two ways:

1. **Via the Setup page** (recommended) — entered during first-time setup
2. **Via environment variable** — set `VAULT_PASSWORD` in docker-compose.yaml

The password is stored in `database.json` and written to `/tmp/.vault_pass.txt` on startup. All Ansible commands use `--vault-password-file /tmp/.vault_pass.txt`.
