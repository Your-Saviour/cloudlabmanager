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
- Clicking Deploy opens a **Dry-Run Preview** modal before executing (see below)
- Non-deploy scripts (e.g., add-users) bypass the preview and use the existing input modal or direct execution flow

### Dry-Run Preview
- Triggered when clicking Deploy on any service — intercepts the deploy action
- Fetches `POST /api/services/{name}/dry-run` and displays the execution plan
- **Loading state**: skeleton placeholders while the dry-run runs
- **Cost estimate**: large dollar amount with per-instance breakdown (mirrors CostsPage styling)
- **Instance specs**: table showing label, hostname, plan, region, OS for each instance
- **DNS records**: predicted A records that will be created in Cloudflare
- **SSH keys**: key type, location, and name from instance.yaml
- **Validation checks**: each check shown with pass/warn/fail status badge
- **Overall status badge**: green (pass), yellow (warn), or red (fail)
- Deploy button is **disabled** when any validation has `fail` status
- Deploy button uses `variant="destructive"` styling when there are warnings
- Cancel closes the modal with no action; Deploy closes the modal and proceeds with the original deploy flow
- Error state shown if the dry-run API returns an error
- Uses wider modal (`max-w-2xl`) to accommodate tables and multiple sections
- Component: `components/services/DryRunPreview.tsx`

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
- **Rerun button** — appears for completed or failed jobs (hidden while running). Clicking it creates a new job with the same inputs and navigates to the new job's detail page. Requires `jobs.rerun` permission (enforced server-side; unauthorized users see an error toast).
- **Parent job link** — when a job was created via rerun, displays "Rerun of {parent_job_id}" as a clickable link that navigates to the original job

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

### Schedules
- List of all scheduled jobs with status badge (Enabled/Disabled), name, type, cron expression, last/next run times, and last status
- **Create dialog** with conditional fields per job type: service/script dropdowns for service scripts, inventory type/action dropdowns for inventory actions, task selector for system tasks
- Cron expression input with debounced preview showing next 5 run times
- Edit, delete, and enable/disable toggle from actions dropdown
- **Execution history dialog** — view past runs for a schedule with job ID links, status badges, and timestamps
- Requires `schedules.*` permissions

### Health
- Dedicated `/health` page showing all monitored services
- Summary badges: healthy, unhealthy, degraded, unknown counts
- Expandable service cards with per-check detail table (name, type, target, status, response time, last checked, error)
- Color-coded status indicators with pulse animation for unhealthy services
- "Reload Configs" button (requires `health.manage` permission)
- 15-second auto-refresh
- Loading skeletons during data fetch
- Empty state when no health checks are configured
- Requires `health.view` permission

### Dashboard Health Panel
- "Service Health" stat card showing healthy/total count
- Grid of service cards with status dot, service name, and response time
- Color-coded borders (green for healthy, red for unhealthy)
- Click navigates to `/health` page
- "View All" button linking to health page
- Only renders when health-checked services exist

### Drift Detection
- Dedicated `/drift` page showing infrastructure drift status
- Summary cards: total defined, in sync (green), drifted (amber), missing (red), orphaned (orange)
- Instance table with expandable rows showing configuration diffs, DNS details, and expected/actual state
- Orphaned instances section with orange-bordered cards (hostname, Vultr ID, plan, region, tags)
- "Check Now" button triggers immediate drift check (requires `drift.manage` permission)
- Report history section (collapsible) showing past reports with timestamps and status
- 30-second auto-refresh
- Empty state with "Run First Check" button when no reports exist
- Sidebar link with `GitCompare` icon (requires `drift.view` permission)

### Audit Log
- Cursor-paginated list of all user actions with filtering, search, and export
- **Filter bar**: user dropdown, action category dropdown, date-from/date-to pickers, full-text search input, clear button
- Filter dropdowns populated from `/api/audit/filters` endpoint
- Search input debounced at 300ms to avoid excessive API calls
- **Export dropdown**: download filtered results as CSV or JSON
- Total entry count badge shown next to export button
- **Pagination**: cursor-based with Previous/Next buttons and cursor stack for backward navigation
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
