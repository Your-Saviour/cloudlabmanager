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
- **Pinned Services section** — personalized panel at the top showing only favorited services (see below)
- **Collapsible sections** — each dashboard section (Pinned Services, Stats, Quick Links, Health, Recent Jobs) has a clickable header with chevron toggle; collapsed state persists via user preferences
- **Drag-and-drop section reordering** — sections can be reordered by dragging the grip handle (⠿) on each section header; order persists via user preferences
- **Quick Links reordering** — quick link cards within the Quick Links section can be drag-and-drop reordered independently of section reordering

### Pinned Services
- Renders at the top of the dashboard when the user has pinned services
- Each card shows: service name with status dot, IP address (if running), and action buttons (Deploy, Stop, Config, SSH)
- Deploy/Stop buttons are permission-gated (`services.deploy`, `services.stop`)
- Expandable outputs section per card — shows service URLs as clickable links, credentials with reveal/copy toggle, and plain text values
- Unpin star button removes the service immediately
- Returns `null` (hidden) when no services are pinned
- Shares query cache with Services page for consistent data
- Component: `components/dashboard/PinnedServices.tsx`

### Instances
- Table: hostname, IP, region, plan, tags, status
- "Refresh from Vultr" button — triggers inventory generation job
- Shows last cache timestamp

### Services
- Card grid showing each deployable service
- Each card shows instance specs (label, plan, region) from instance.yaml
- **Pin/unpin toggle** — star icon in the top-right of each service card; click to pin (filled amber star) or unpin (outline star) a service to the dashboard; state persists via user preferences API
- "Deploy" and "Stop" buttons with confirmation dialogs
- Clicking Deploy opens a **Dry-Run Preview** modal before executing (see below)
- Non-deploy scripts (e.g., add-users) bypass the preview and use the existing input modal or direct execution flow
- **Multi-select**: checkbox on each service card for bulk operations
- **Select All / Deselect All** button in the page header
- **Bulk Action Bar**: floating bar at the bottom when services are selected, with Deploy and Stop actions (respects permissions)
- Bulk actions show confirmation dialogs with selected count and navigate to the parent job page on completion

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
- Bulk parent jobs display a **bulk** badge next to the action name
- Click a job to view its detail page

### Job Detail
- Full ansible output displayed in a terminal-style `<pre>` block
- Auto-scrolling, auto-updating (polls every 1s while job is running)
- Status badge updates when job completes
- **Rerun button** — appears for completed or failed jobs (hidden while running). Clicking it creates a new job with the same inputs and navigates to the new job's detail page. Requires `jobs.rerun` permission (enforced server-side; unauthorized users see an error toast).
- **Parent job link** — when a job was created via rerun, displays "Rerun of {parent_job_id}" as a clickable link that navigates to the original job
- **Child Jobs panel** — for bulk parent jobs, displays a "Child Jobs" card below the output showing each child job's status badge, service/action name, and a "View" link. Auto-refreshes every 3 seconds while the parent job is running.

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

### Quick Links (Dashboard)
- Displays auto-discovered service URLs and user-created custom links in a responsive grid
- Each card has a grip handle for drag-and-drop reordering (uses `@dnd-kit` with `rectSortingStrategy`)
- **Custom links**: dashed border style with "custom" badge; 3-dot dropdown menu with Edit and Delete actions
- **Add custom link**: dashed card with plus icon at the end of the grid; opens a dialog with Label, URL fields and live preview
- Custom link dialog supports both add and edit modes with `react-hook-form` + `zod` validation
- Auto-discovered links are read-only (no edit/delete controls)
- Link order persists via user preferences (`quick_links.order` array)
- Component: `components/dashboard/QuickLinksSection.tsx`, `components/dashboard/AddLinkDialog.tsx`

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
- **Multi-select**: checkbox column in the DataTable for selecting multiple objects
- **Bulk Action Bar**: floating bar with actions based on inventory type config — Add Tags, Remove Tags, Delete, and type-specific actions (Destroy, Stop)
- Tag picker dialog for bulk tag add/remove operations
- Confirmation dialogs for destructive bulk actions
- Skipped items (due to RBAC) shown via warning toast

### Portal
- Unified service access launchpad at `/portal` (requires `portal.view` permission)
- Sidebar link with Compass icon between Dashboard and Services
- **Grid/list toggle** — grid mode shows full service cards, list mode shows compact single-row entries
- **Search** — filters across service name, hostname, FQDN, IP, and tags (case-insensitive)
- **Grouping** — group by none, tag, or region with labeled section headers
- **Service cards** (grid view):
  - 3px colored status strip (green=running, amber=suspended, gray=stopped)
  - Display name, health badge (healthy/unhealthy/degraded/unknown), power status
  - Data cells: hostname, IP address, region
  - Prominent FQDN link with globe icon
  - Tags as outline badges
  - **Outputs section**: URL outputs as clickable links, credentials with blur/reveal toggle and copy-to-clipboard, plain text values
  - **"Open in Browser" button** — opens first URL output in new tab
  - **Connection Guide** — expandable section with SSH command (copy button), web URL, FQDN
  - **SSH Terminal button** — opens modal with embedded xterm.js terminal via WebSocket (only for running services with hostname and IP)
  - **Bookmarks** — per-user custom links and notes with add/edit/delete controls (requires `portal.bookmarks.edit` permission)
- **List view** — compact rows with status dot, name, FQDN/IP link, health badge, region, and action icons (SSH copy, credential copy, open in browser)
- Loading skeletons for both grid and list modes
- Empty state when no services exist or no search results match
- Components: `pages/portal/PortalPage.tsx`, `components/portal/ServicePortalCard.tsx`, `components/portal/CredentialDisplay.tsx`, `components/portal/ConnectionGuide.tsx`, `components/portal/BookmarkSection.tsx`, `components/portal/SSHTerminalModal.tsx`

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
