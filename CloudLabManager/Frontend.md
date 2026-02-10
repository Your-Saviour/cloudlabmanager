Go to [[Introduction]]

## Overview

The frontend is a single-page application (SPA) built with vanilla HTML, CSS, and JavaScript. No build step, no npm. Uses Pico CSS from CDN for base styling.

Served as static files from `/static/` by FastAPI. The root URL `/` returns `index.html`.

## Technology

- **CSS Framework**: Pico CSS (dark theme)
- **Routing**: Hash-based (`#dashboard`, `#services`, etc.)
- **Auth**: JWT stored in `localStorage`, sent as `Authorization: Bearer` header
- **Live output**: Polls `/api/jobs/{id}` every 1 second for running jobs

## Views

### Login
Username/password form. Shown when no valid token exists.

### Setup
First-boot only. Creates admin account and sets the Ansible vault password. Automatically redirects here if no users exist.

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

### Jobs
- List of all jobs sorted by most recent
- Each entry shows service name, action, and status badge
- Click a job to view its detail page

### Job Detail
- Full ansible output displayed in a terminal-style `<pre>` block
- Auto-scrolling, auto-updating (polls every 1s while job is running)
- Status badge updates when job completes

## Files

| File | Purpose |
|------|---------|
| `app/static/index.html` | SPA shell, nav bar, Pico CSS import |
| `app/static/style.css` | Terminal, badges, cards, stat grid, confirmation dialog |
| `app/static/app.js` | All frontend logic: routing, API calls, view rendering |
