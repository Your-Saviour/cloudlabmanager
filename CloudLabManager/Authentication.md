Go to [[Introduction]]

## Overview

CloudLabManager uses JWT (JSON Web Tokens) for authentication with a full RBAC permission system. Tokens are issued on login and expire after 24 hours.

For role-based access control details, see [[RBAC]].

## First-Time Setup

On first boot, no users exist. The frontend detects this via `GET /api/auth/setup-required` and shows the Setup page. Setup creates the initial admin account (with Super Admin role) and sets the Ansible vault password in one step.

After setup, the `/api/auth/setup` endpoint is permanently disabled.

## Login Flow

1. User submits username + password to `POST /api/auth/login`
2. Server verifies password against bcrypt hash stored in the `users` table
3. If MFA is **not** enabled: server returns a JWT signed with a secret key (auto-generated on first boot, stored in `app_metadata`)
4. If MFA **is** enabled: server returns `{ "mfa_required": true, "mfa_token": "..." }` — a 5-minute partial JWT with `purpose: "mfa"`
5. Frontend shows a TOTP verification screen; user submits the 6-digit code (or a backup code) to `POST /api/auth/mfa/verify`
6. Server validates the MFA token + TOTP code and returns the full JWT
7. Frontend stores the token in `localStorage`
8. All subsequent API requests include `Authorization: Bearer <token>`

## Multi-Factor Authentication (MFA)

CloudLabManager supports TOTP-based two-factor authentication. When enabled, users must provide a 6-digit code from their authenticator app (Google Authenticator, Authy, etc.) after password verification.

See [[MFA Authentication]] in the CloudLab docs for the full user and admin guide.

### Enrollment Flow

1. User navigates to Profile → Two-Factor Authentication section
2. `POST /api/auth/mfa/enroll` generates a TOTP secret and returns a QR code (base64 PNG)
3. User scans the QR code with their authenticator app
4. User enters a valid 6-digit code to `POST /api/auth/mfa/confirm`
5. Backend verifies the code, enables MFA, and returns 8 single-use backup codes

### MFA Verification

- TOTP codes allow 1 window of time drift (30 seconds)
- Backup codes can be used instead of TOTP if the authenticator device is unavailable
- Each backup code is single-use (consumed after verification)
- MFA tokens expire after 5 minutes

### Admin MFA Reset

Admins with `users.mfa_reset` permission can force-disable MFA for locked-out users via `DELETE /api/users/{user_id}/mfa`. This is audit-logged as `mfa_admin_reset`.

### Implementation Details

- **TOTP library**: pyotp
- **QR codes**: qrcode[pil] (base64-encoded PNG)
- **Secret encryption**: Fernet symmetric encryption, key derived from the app's existing `secret_key`
- **Backup codes**: 8 uppercase hex codes (8 chars each), stored as bcrypt hashes
- **MFA tokens**: 5-minute JWT with `purpose: "mfa"` to differentiate from access tokens
- **Database tables**: `user_mfa` (per-user MFA state + encrypted TOTP secret), `mfa_backup_codes` (hashed backup codes)

## User Invitation Flow

1. An admin creates a new user via `POST /api/users` with username and email
2. A 72-hour invite token is generated and stored in the `invite_tokens` table
3. An invitation email is sent via Sendamatic with a link to `/#accept-invite-{token}`
4. The user clicks the link and sets their password via `POST /api/auth/invite/{token}`
5. The invite token is marked as used and the user account is activated

Admins can resend invites via `POST /api/users/{id}/resend-invite`.

## Password Reset Flow

1. A password reset is requested via `POST /api/auth/forgot-password` with the user's email
2. A 1-hour reset token is generated and stored in the `password_reset_tokens` table
3. A reset email is sent with a link to `/#reset-password-{token}`
4. The user clicks the link and sets a new password via `POST /api/auth/password-reset/{token}`

CLI reset is also available:

```bash
docker compose exec cloudlabmanager python3 /app/reset_password.py --username jake
```

## RBAC Integration

All protected API routes use FastAPI dependencies for authorization:

- `Depends(get_current_user)` — validates the JWT and returns the `User` object
- `Depends(require_permission("category.action"))` — validates JWT + checks the user has the required permission

Permissions are checked against the user's roles. See [[RBAC]] for the full permission model.

## Audit Logging

All authenticated actions are logged to the `audit_log` table with:

- User ID and username
- Action performed (e.g., `service.deploy`, `user.create`)
- Resource affected
- IP address
- Timestamp

See [[API Endpoints#Audit]] for the audit log endpoint.

## Implementation Details

- **JWT library**: python-jose (HS256 algorithm)
- **Password hashing**: passlib with bcrypt (pinned to bcrypt < 4.1 for compatibility)
- **Secret key**: 32-byte hex token, generated once and stored in `app_metadata` table
- **Token expiry**: Access tokens 24 hours, invite tokens 72 hours, reset tokens 1 hour
- **Protected routes**: Use `Depends(get_current_user)` or `Depends(require_permission(...))` FastAPI dependency

## Vault Password

The Ansible vault password is needed to decrypt `secrets.yml` in the CloudLab repo. It can be set in two ways:

1. **Via the Setup page** (recommended) — entered during first-time setup
2. **Via environment variable** — set `VAULT_PASSWORD` in docker-compose.yaml

The password is stored in `app_metadata` and written to `/tmp/.vault_pass.txt` on startup. All Ansible commands use `--vault-password-file /tmp/.vault_pass.txt`.
