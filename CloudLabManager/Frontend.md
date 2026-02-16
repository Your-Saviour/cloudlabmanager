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
- **Cross-link chips** — compact badge chips below the tags row showing: health status (colored dot), webhook count, schedule count, and monthly cost. Clicking a chip navigates to the relevant page pre-filtered to that service (e.g., `/webhooks?service=n8n-server`). Cost chip is permission-gated behind `costs.view`. Data fetched from `GET /api/services/summaries` with 30-second auto-refresh. Component: `components/services/ServiceCrossLinks.tsx`
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
- **Provenance badges** — small outline badges in the Action column indicate how the job was triggered: `schedule` for scheduled jobs, `webhook` for webhook-triggered jobs, `rerun` for rerun jobs. Manual jobs have no badge. Badges use the same styling as existing bulk/deployment badges.
- Click a job to view its detail page

### Job Detail
- Full ansible output displayed in a terminal-style `<pre>` block
- Auto-scrolling, auto-updating (polls every 1s while job is running)
- Status badge updates when job completes
- **Rerun button** — appears for completed or failed jobs (hidden while running). Clicking it creates a new job with the same inputs and navigates to the new job's detail page. Requires `jobs.rerun` permission (enforced server-side; unauthorized users see an error toast).
- **Provenance section** — always visible, shows how the job was triggered:
  - **Schedule-triggered**: "Triggered by schedule {name}" with clickable link to `/schedules` (or "deleted schedule" in italic if the schedule no longer exists)
  - **Webhook-triggered**: "Triggered by webhook {name}" with clickable link to `/webhooks` (or "deleted webhook" in italic if the webhook no longer exists)
  - **Rerun**: "Rerun of {job_id}" as a clickable link to the parent job
  - **Manual**: "Triggered manually" as fallback when no automation source is set
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
- Supports `?service=<name>` query parameter to filter by service (shows removable filter badge)
- Requires `schedules.*` permissions

### Notifications
- Tabbed settings page with **Notification Rules**, **Channels**, and **Email** tabs
- **Email tab** — shows the active email transport (SMTP or Sendamatic) with a code badge, configuration status badge, and SMTP connection details (host, port, TLS) when applicable
- "Send Test Email" button sends a test email to the current user's address (requires `notifications.channels.manage` permission and a configured transport)
- Guidance messages when no transport is configured, with info about environment variable configuration
- Hooks: `useEmailTransportStatus()`, `useTestEmail()` in `hooks/useNotificationRules.ts`
- Component: `EmailTab` in `pages/notifications/NotificationRulesPage.tsx`

### Snapshots
- Dedicated `/snapshots` page showing all Vultr instance snapshots (requires `snapshots.view` permission)
- DataTable with columns: instance name, description, status badge (`pending`/`complete`), size, age
- **Take Snapshot** button — opens dialog to select an instance and enter a description; creates a job
- **Sync** button — manually triggers snapshot metadata sync from Vultr
- **Restore** action (row dropdown, only for `complete` snapshots) — dialog with label, hostname, plan selector (fetches from `/api/costs/plans`), and region selector (Sydney/Melbourne)
- **Delete** action (row dropdown) — destructive confirmation dialog
- Permission-gated action buttons (`snapshots.create`, `snapshots.delete`, `snapshots.restore`)
- 15-second auto-refresh to pick up status changes
- After create/delete/restore, navigates to the job detail page
- Sidebar link with Camera icon (between Costs and Health)
- Component: `pages/snapshots/SnapshotsPage.tsx`

### Inventory Detail — Snapshots Tab
- Server inventory objects show a **Snapshots** tab on their detail page
- Lists snapshots filtered to the current instance
- Same Take Snapshot, Restore, and Delete actions as the main Snapshots page
- Tab only appears for server-type inventory objects

### Cost Dashboard — Snapshot Storage
- **Snapshot Storage** summary card on the Costs page showing total GB, snapshot count, and monthly cost estimate ($0.05/GB/month)
- Grid layout expanded to 4 columns at `lg` breakpoint to accommodate the new card
- Only renders when `snapshot_storage` data is present in the API response

### Health
- Dedicated `/health` page showing all monitored services
- Summary badges: healthy, unhealthy, degraded, unknown counts
- Expandable service cards with per-check detail table (name, type, target, status, response time, last checked, error)
- Color-coded status indicators with pulse animation for unhealthy services
- "Reload Configs" button (requires `health.manage` permission)
- 15-second auto-refresh
- Loading skeletons during data fetch
- Empty state when no health checks are configured
- Supports `?service=<name>` query parameter to filter by service (shows removable filter badge)
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

### Inventory Detail — Job History
- **Job History tab** on each inventory object's detail page (alongside Details, Tags, Actions, ACLs)
- Shows all jobs that targeted the object, fetched via `GET /api/jobs?object_id={id}` with 10-second polling
- DataTable columns: Status (badge), Action (clickable link to job detail), Triggered By, Started (relative time), Duration
- Empty state message when no jobs exist for the object
- **Last job badge** in the detail page header — shows the most recent job's status and relative timestamp
- Badge is clickable, navigating to the job's detail page
- Badge only renders when job history exists (gracefully hidden otherwise)

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

### Command Palette
- Opened with `Cmd+K` (macOS) or `Ctrl+K` (Windows/Linux)
- **Unified navigation** — auto-generates entries from the shared route definitions used by the Sidebar, so new pages are automatically included (15+ routes)
- **Search groups**: Navigation, Services, Inventory, Actions, Admin, Quick Actions
- **Fuzzy search with aliases** — partial word matching plus keyword aliases (e.g., "cron" → Schedules, "budget" → Costs, "drift" → Drift Detection, "links" → Portal)
- **Dynamic service items** — fetches deployed services from the API, shows name and Running/Stopped status sublabel. Reuses the `['inventory', 'service']` query cache with 30-second stale time
- **Dynamic inventory items** — lists all registered inventory types with links to their detail pages
- **Action commands** — contextual shortcuts: Refresh Costs, Run Drift Check, Reload Health Checks, Export Audit Log, Stop All Services, Create Webhook, Create Schedule, Invite User
- **Permission filtering** — all navigation, service, and action items are filtered by the current user's RBAC permissions. Groups are hidden entirely when no items pass the filter
- **Recent items** — tracks the last 10 palette selections in localStorage (key: `cloudlab-command-palette`) using a Zustand persisted store. Recent group appears at the top when the search is empty, showing item icon, label, and relative timestamp ("Just now", "5m ago", "2h ago", "3d ago"). Re-selecting an item moves it to the front (deduplication)
- Shared route definitions: `src/lib/routes.ts` (used by both Sidebar and CommandPalette)
- Action registry: `src/lib/commandRegistry.ts`
- Recent store: `src/stores/commandPaletteStore.ts`
- Component: `components/layout/CommandPalette.tsx`

### Help Menu
- `?` (HelpCircle) icon button in the header, positioned before the notification bell
- DropdownMenu with items: "Request a Feature" (MessageSquare icon), "Report a Bug" (Bug icon), separator, "View Feedback" (navigates to `/feedback`)
- Clicking "Request a Feature" or "Report a Bug" opens the `SubmitFeedbackModal` with the appropriate type pre-selected
- Component: `components/layout/HelpMenu.tsx`

### Submit Feedback Modal
- Reusable modal for submitting feature requests or bug reports
- Fields: Title (required, max 200 chars), Description (required textarea), Priority (Low/Medium/High dropdown, defaults to Medium), Screenshot (optional file upload, max 5MB)
- Uses `react-hook-form` + `zod` validation (matches `ReportBugModal` pattern)
- Submit flow: POST JSON to `/api/feedback`, then uploads screenshot via `/api/feedback/{id}/screenshot` if provided
- Placeholder text varies by type (feature request vs bug report)
- Component: `components/feedback/SubmitFeedbackModal.tsx`

### Feedback Page
- Dedicated `/feedback` page for viewing and managing feedback submissions
- **DataTable** with columns: type icon (lightbulb for features, bug icon for bugs), title, priority badge, status badge, submitted by (admin only), date
- **Tab switcher** (All Requests / My Requests) — visible only for users with `feedback.view_all` permission
- **Filters**: type filter (All/Features/Bugs) and status filter (All/New/Reviewed/Planned/In Progress/Completed/Declined)
- **Action buttons**: "Request Feature" and "Report Bug" in the page header open the `SubmitFeedbackModal`
- **Detail dialog**: click a title to open a dialog showing full description, screenshot (if available), priority/status badges
  - Admin controls (with `feedback.manage`): status dropdown, admin notes textarea, Save/Cancel buttons
  - Non-admin: read-only view with admin notes shown if set
- Non-admin users without `feedback.view_all` only see their own feedback (tab switcher hidden, `my_requests=true` always sent)
- Sidebar link with `MessageSquareMore` icon under Admin section (requires `feedback.view_all` permission)
- Component: `pages/feedback/FeedbackPage.tsx`

## Files

| File | Purpose |
|------|---------|
| `app/static/index.html` | SPA shell, nav bar, Pico CSS import |
| `app/static/style.css` | Terminal, badges, cards, stat grid, confirmation dialog |
| `app/static/app.js` | All frontend logic: routing, API calls, view rendering |
