# CloudLabManager Feature Ideas

## 1. Infrastructure Blueprints & Templates

**What it adds:** A blueprint system that lets users define reusable multi-service deployment templates. Instead of deploying services one at a time, a blueprint packages multiple services, their configurations, instance specs, and networking rules into a single deployable unit. Blueprints are stored as versioned YAML files and can be shared between users.

**How it benefits the user:**
- Deploy an entire lab environment (e.g., Splunk + Velociraptor + jump hosts + n8n) with one click instead of running 4+ separate deployments
- Standardize environments across teams — everyone gets the same infrastructure from the same blueprint
- Quickly tear down and redeploy entire environments for training, testing, or incident response exercises
- Version blueprints so you can roll back to a known-good configuration

**How it incorporates into the project:**
- Extends the existing service discovery system — blueprints reference services already defined in `services/`
- Uses the job tracking system to orchestrate sequential and parallel deployments across multiple services
- Integrates with the inventory system by auto-creating inventory objects for all deployed resources as a linked group
- Leverages existing RBAC — blueprint access is controlled through role permissions, and tag-based permissions can restrict which blueprints users can deploy
- Stored in a new `blueprints/` directory alongside the existing `services/` structure

---

## 2. Scheduled Operations & Maintenance Windows

**What it adds:** A scheduler that lets users define time-based automation rules for their infrastructure. This includes scheduled instance start/stop (e.g., spin up lab environments at 9am, tear them down at 6pm), recurring playbook runs (e.g., weekly security scans), and maintenance windows that temporarily suppress alerts and block deployments during planned downtime.

**How it benefits the user:**
- Significant cost savings by automatically stopping instances outside working hours — cloud VMs bill by the hour, so a 9-to-5 schedule cuts costs by ~65%
- Hands-off recurring maintenance — run hardening playbooks, rotate credentials, or sync configurations on a schedule without manual intervention
- Maintenance windows prevent accidental deployments during planned downtime and give users visibility into when infrastructure is intentionally unavailable
- Timezone-aware scheduling for distributed teams

**How it incorporates into the project:**
- Builds on the existing `start-instances.yaml` and `stop-instances.yaml` playbooks — scheduled actions call the same Ansible automation that manual operations use
- Scheduled jobs appear in the existing job tracking and audit log systems, maintaining full visibility
- Schedule definitions are stored in SQLite alongside existing models, with a new lightweight scheduler running as an async background task in the FastAPI process
- RBAC controls who can create, modify, and delete schedules — a user can only schedule operations on resources they have permission to manage
- Cost tracking integration — the cost dashboard can project savings from scheduled shutdowns

---

## 3. Live Infrastructure Dashboard with Health Monitoring

**What it adds:** A real-time dashboard that displays infrastructure health at a glance. Each deployed instance shows live status indicators (up/down/degraded), resource utilization (CPU, memory, disk), service health checks (HTTP probes, port checks), and uptime history. The dashboard auto-refreshes via WebSocket and supports configurable alert thresholds that trigger notifications.

**How it benefits the user:**
- Instant visibility into whether deployed services are actually running and healthy — not just whether the VM exists
- Catch problems before they escalate: disk filling up, services crashing, instances becoming unreachable
- Reduce context-switching — users don't need to SSH into each machine or check Vultr's dashboard separately
- Alert notifications (email via Sendamatic, or in-app) let users respond to issues without constantly watching the dashboard
- Historical uptime data helps with capacity planning and identifying recurring issues

**How it incorporates into the project:**
- Extends the existing instance management routes with health check endpoints
- Health probes run as lightweight async tasks in FastAPI, using the existing SSH infrastructure (asyncssh) to query remote hosts
- Status data feeds into the inventory system — each server inventory object gets health metadata fields
- WebSocket infrastructure already exists for SSH terminals and job streaming — health updates use the same transport
- Alert thresholds integrate with the email service (Sendamatic) already configured for user invitations
- RBAC ensures users only see health data for instances they have permission to view

---

## 4. Deployment Rollback & Snapshot Management

**What it adds:** Automatic pre-deployment snapshots of Vultr instances and a one-click rollback system. Before any service deployment runs, CloudLabManager triggers a Vultr snapshot via their API. If a deployment fails or causes issues, users can roll back to the pre-deployment state. The system tracks snapshot history per instance, manages snapshot retention policies, and provides a comparison view showing what changed between snapshots.

**How it benefits the user:**
- Eliminates the fear of breaking a working environment — every deployment has a safety net
- Faster recovery from failed deployments: rollback in minutes instead of reprovisioning and redeploying from scratch
- Snapshot history provides a timeline of infrastructure changes, making it easy to identify when something broke
- Retention policies prevent snapshot costs from spiraling — automatically clean up old snapshots based on age or count
- Enables experimentation — users can try risky configurations knowing they can always roll back

**How it incorporates into the project:**
- Uses the Vultr API (already authenticated via `vultr_api_key` in vault) to create and manage snapshots
- Pre-deployment snapshot creation hooks into the existing `ansible_runner.py` — snapshots are taken automatically before playbook execution
- Snapshot metadata is stored as inventory objects using the existing type-driven inventory system, linked to their parent server objects
- Rollback operations appear in the job tracking system with full audit logging
- RBAC controls rollback permissions separately from deployment permissions — an operator might deploy but only an admin can roll back
- The existing cost tracking system can include snapshot storage costs in its reports

---

## 5. Multi-Environment Workspace Isolation

**What it adds:** Workspace support that lets users create isolated environments (e.g., "Production", "Staging", "Training Lab", "Red Team Exercise") within a single CloudLabManager instance. Each workspace has its own set of deployed instances, inventory, configuration overrides, and access controls. Users can be assigned to specific workspaces, and resources in one workspace are invisible to users of another.

**How it benefits the user:**
- Run multiple independent environments without deploying separate CloudLabManager instances
- Training scenarios: spin up identical lab environments for each student or team, each isolated from the others
- Environment promotion: test deployments in a staging workspace before applying the same configuration to production
- Security isolation for sensitive operations — a red team exercise workspace is completely separate from production infrastructure
- Simplified cleanup — delete a workspace and all its associated resources are torn down automatically

**How it incorporates into the project:**
- Workspaces are implemented as a layer on top of the existing tag-based inventory system — each workspace is essentially a super-tag that scopes all queries
- The RBAC system already supports tag-based permissions, so workspace isolation maps naturally to existing permission checks
- Service deployments are scoped to a workspace, with workspace-specific configuration overrides stored in the database
- Instance definitions can be templated per workspace (e.g., staging uses smaller plans than production)
- The audit log captures workspace context, so administrators can review activity per environment
- Workspace templates can build on the blueprint system (Feature #1) — create a workspace from a blueprint for one-click environment provisioning
- The frontend adds a workspace switcher to the navigation, with the current workspace persisted in Zustand state
