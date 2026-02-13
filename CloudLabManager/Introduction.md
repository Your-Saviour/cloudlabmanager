CloudLabManager is a web-based management interface for [[CloudLab]] infrastructure. It provides a browser UI and REST API for deploying services, managing Vultr instances, running Ansible playbooks, managing users with role-based access control, and tracking infrastructure inventory — without needing direct shell access to the Ansible container.

## Quick Links

- [[API Endpoints]]
- [[Configuration Files]]
- [[Architecture]]
- [[Frontend]]
- [[Authentication]]
- [[RBAC]]
- [[Inventory System]]
- [[Ansible Integration]]
- [[Testing]]

## Getting Started

```bash
# Build and start
docker compose up -d --build

# Open in browser
http://localhost:8000
```

On first boot you'll see a **Setup** page where you create an admin account and enter the Ansible vault password. After that, log in and you're ready to deploy services.

## What It Does

1. Clones the CloudLab repo on startup
2. Creates symlinks so Ansible playbook paths resolve correctly
3. Discovers available services from `cloudlab/services/`
4. Runs Ansible playbooks via async subprocess (same flow as the shell scripts)
5. Tracks deployment jobs with live output streaming
6. Caches Vultr instance inventory on demand
7. Manages users with role-based access control (RBAC) and email invitations
8. Provides a flexible inventory system with type-driven objects, tags, and ACLs
9. Supports WebSocket SSH terminals to managed servers
10. Logs all user actions to an audit trail
11. Sends email notifications for invitations and password resets
12. Schedules recurring jobs via cron expressions with execution history tracking
