Go to [[Introduction]]

## Overview

The frontend is a single-page application (SPA) built with vanilla HTML, CSS, and JavaScript. No build step, no npm. Uses Pico CSS from CDN for base styling.

Served as static files from `/static/` by FastAPI. The root URL `/` returns `index.html`.

## Technology

- **CSS Framework**: Pico CSS (dark theme)
- **Routing**: Hash-based (`#dashboard`, `#services`, etc.)
- **Auth**: JWT stored in `localStorage`, sent as `Authorization: Bearer` header
- **Live output**: Polls `/api/jobs/{id}` every 1 second for running jobs
- **WebSocket**: Used for SSH terminals and real-time action output

## Views

### Login
Username/password form. Shown when no valid token exists.

### Setup
First-boot only. Creates admin account and sets the Ansible vault password. Automatically redirects here if no users exist.

### Accept Invite
Shown when opening an invite link (`#accept-invite-{token}`). Sets password for an invited user.

### Password Reset
Shown when opening a reset link (`#reset-password-{token}`). Sets a new password.

### Dashboard
- Stat cards: service count, running/completed/failed job counts
- Recent jobs list (last 10)
- "Stop All Instances" button with confirmation dialog

### Instances
- Table: hostname, IP, region, plan, tags, status
- "Refresh from Vultr" button — triggers inventory generation job
- Shows last cache timestamp

### Services
- Card grid showing each deployable service
- Each card shows instance specs (label, plan, region) from instance.yaml
- "Deploy" and "Stop" buttons with confirmation dialogs
- Clicking Deploy starts a job and navigates to the job detail view

### Config Editor
- Edit service configuration files (instance.yaml, config.yaml, scripts.yaml) in-browser
- YAML syntax validation before saving

### File Manager
- Browse and manage files in service `inputs/` and `outputs/` directories
- Upload, download, edit, and delete files

### Jobs
- List of all jobs sorted by most recent
- Each entry shows service name, action, and status badge
- Click a job to view its detail page

### Job Detail
- Full ansible output displayed in a terminal-style `<pre>` block
- Auto-scrolling, auto-updating (polls every 1s while job is running)
- Status badge updates when job completes

### User Management
- List of all users with status (active, invited, inactive)
- Invite new users (sends email)
- Edit user profiles and role assignments
- Resend invitations, deactivate accounts

### Role Management
- List of all roles with assigned permission counts
- Create custom roles with selected permissions
- Edit role permissions (grouped by category)
- Cannot modify or delete system roles

### Audit Log
- Paginated list of all user actions
- Shows: user, action, resource, IP address, timestamp
- Requires `system.audit_log` permission

### Inventory Management
- Tab-based view per inventory type (Servers, Services, Users, Deployments)
- Object list with search, tag filtering, and pagination
- Create/edit/delete objects with type-specific field forms
- Tag management (assign tags, create new tags with colors)
- ACL management per object (role-based allow/deny rules)
- Execute configurable actions on objects

### SSH Terminal
- Opens from inventory actions on server objects
- Full interactive terminal via WebSocket
- Uses AsyncSSH on the server side
- Credentials resolved from service inventory files

## Files

| File | Purpose |
|------|---------|
| `app/static/index.html` | SPA shell, nav bar, Pico CSS import |
| `app/static/style.css` | Terminal, badges, cards, stat grid, confirmation dialog |
| `app/static/app.js` | All frontend logic: routing, API calls, view rendering |
