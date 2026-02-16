import asyncio
import json
import logging
from datetime import datetime, timezone

from croniter import croniter
from database import SessionLocal, ScheduledJob, JobRecord

logger = logging.getLogger("scheduler")


class Scheduler:
    """Background scheduler that checks for due scheduled jobs and triggers them."""

    def __init__(self, runner):
        self.runner = runner  # AnsibleRunner instance
        self._task: asyncio.Task | None = None
        self._running = False
        self.check_interval = 30  # seconds

    def start(self):
        """Start the scheduler background loop."""
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Scheduler started (interval=%ds)", self.check_interval)

    async def stop(self):
        """Stop the scheduler gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Scheduler stopped")

    async def _loop(self):
        """Main scheduler loop — check for due jobs every `check_interval` seconds."""
        while self._running:
            try:
                await self._check_and_dispatch()
                await self._update_completed_schedules()
            except Exception:
                logger.exception("Scheduler tick error")
            await asyncio.sleep(self.check_interval)

    async def _check_and_dispatch(self):
        """Find all enabled schedules that are due and dispatch them."""
        now = datetime.now(timezone.utc)
        session = SessionLocal()
        try:
            due_schedules = (
                session.query(ScheduledJob)
                .filter(
                    ScheduledJob.is_enabled == True,
                    ScheduledJob.next_run_at != None,
                    ScheduledJob.next_run_at <= now,
                )
                .all()
            )

            for schedule in due_schedules:
                try:
                    await self._dispatch(schedule, session)
                except Exception:
                    logger.exception("Failed to dispatch schedule %d (%s)", schedule.id, schedule.name)

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def _dispatch(self, schedule: ScheduledJob, session):
        """Dispatch a single scheduled job."""
        # Skip-if-running check
        if schedule.skip_if_running and schedule.last_job_id:
            if self._is_job_running(schedule.last_job_id):
                logger.info(
                    "Skipping schedule %d (%s) — previous job %s still running",
                    schedule.id, schedule.name, schedule.last_job_id,
                )
                # Advance next_run_at so we don't keep trying every tick
                schedule.next_run_at = self._next_run(schedule.cron_expression)
                return

        logger.info("Dispatching schedule %d (%s)", schedule.id, schedule.name)

        job = None
        inputs = json.loads(schedule.inputs) if schedule.inputs else {}

        sched_username = f"scheduler:{schedule.name}"[:30]

        if schedule.job_type == "service_script":
            job = await self.runner.run_script(
                schedule.service_name,
                schedule.script_name,
                inputs,
                user_id=schedule.created_by,
                username=sched_username,
            )

        elif schedule.job_type == "system_task":
            if schedule.system_task == "refresh_instances":
                job = await self.runner.refresh_instances(
                    user_id=schedule.created_by,
                    username=sched_username,
                )
            elif schedule.system_task == "refresh_costs":
                job = await self.runner.refresh_costs(
                    user_id=schedule.created_by,
                    username=sched_username,
                )
            elif schedule.system_task == "drift_check":
                from drift_checker import run_drift_check
                await run_drift_check(triggered_by="schedule")
                # drift_check manages its own state; no JobRecord returned
                schedule.last_run_at = datetime.now(timezone.utc)
                schedule.last_status = "completed"
                schedule.next_run_at = self._next_run(schedule.cron_expression)
                return
            elif schedule.system_task == "personal_jumphost_cleanup":
                from jumphost_cleanup import check_and_cleanup_expired
                destroyed = await check_and_cleanup_expired(self.runner)
                schedule.last_run_at = datetime.now(timezone.utc)
                schedule.last_status = "completed"
                schedule.next_run_at = self._next_run(schedule.cron_expression)
                if destroyed:
                    logger.info("TTL cleanup destroyed %d host(s): %s", len(destroyed), ", ".join(destroyed))
                return

        elif schedule.job_type == "inventory_action":
            job = await self._dispatch_inventory_action(schedule, inputs)

        if job:
            job.schedule_id = schedule.id
            schedule.last_run_at = datetime.now(timezone.utc)
            schedule.last_job_id = job.id
            schedule.last_status = "running"

        # Always advance next_run_at
        schedule.next_run_at = self._next_run(schedule.cron_expression)

    async def _dispatch_inventory_action(self, schedule: ScheduledJob, inputs: dict):
        """Dispatch an inventory action schedule."""
        from database import InventoryObject
        from type_loader import load_type_configs

        session = SessionLocal()
        try:
            # Load object data if object_id is set
            obj_data = {}
            if schedule.object_id:
                obj = session.query(InventoryObject).filter_by(id=schedule.object_id).first()
                if obj:
                    obj_data = json.loads(obj.data) if isinstance(obj.data, str) else obj.data

            # Build a minimal action_def
            action_def = {
                "name": schedule.action_name,
                "type": "script",  # default
                "_inputs": inputs,
            }

            # Try to look up the full action definition from type configs
            configs = load_type_configs()
            for config in configs:
                if config["slug"] == schedule.type_slug:
                    for action in config.get("actions", []):
                        if action["name"] == schedule.action_name:
                            action_def.update(action)
                            action_def["_inputs"] = inputs
                            break
                    break

            job = await self.runner.run_action(
                action_def,
                obj_data,
                schedule.type_slug,
                user_id=schedule.created_by,
                username=f"scheduler:{schedule.name}"[:30],
                object_id=schedule.object_id,
            )
            return job
        finally:
            session.close()

    def _is_job_running(self, job_id: str) -> bool:
        """Check if a job is currently running (in-memory check first, then DB)."""
        # In-memory jobs
        if job_id in self.runner.jobs:
            return self.runner.jobs[job_id].status == "running"
        # Persisted jobs
        session = SessionLocal()
        try:
            record = session.query(JobRecord).filter_by(id=job_id).first()
            return record is not None and record.status == "running"
        finally:
            session.close()

    async def _update_completed_schedules(self):
        """Update last_status for schedules whose last job has finished."""
        session = SessionLocal()
        try:
            running_schedules = (
                session.query(ScheduledJob)
                .filter(ScheduledJob.last_status == "running")
                .all()
            )
            for schedule in running_schedules:
                if not schedule.last_job_id:
                    continue
                new_status = None
                # Check in-memory first
                if schedule.last_job_id in self.runner.jobs:
                    job = self.runner.jobs[schedule.last_job_id]
                    if job.status != "running":
                        schedule.last_status = job.status
                        new_status = job.status
                else:
                    # Check DB
                    record = session.query(JobRecord).filter_by(id=schedule.last_job_id).first()
                    if record and record.status != "running":
                        schedule.last_status = record.status
                        new_status = record.status

                # Fire notification for completed/failed scheduled jobs
                if new_status in ("completed", "failed"):
                    from notification_service import notify, EVENT_SCHEDULE_COMPLETED, EVENT_SCHEDULE_FAILED

                    event_type = EVENT_SCHEDULE_COMPLETED if new_status == "completed" else EVENT_SCHEDULE_FAILED
                    severity = "success" if new_status == "completed" else "error"

                    try:
                        await notify(event_type, {
                            "title": f"Scheduled job {new_status}: {schedule.name}",
                            "body": f"Scheduled job '{schedule.name}' (job {schedule.last_job_id}) has {new_status}.",
                            "severity": severity,
                            "action_url": f"/jobs/{schedule.last_job_id}" if schedule.last_job_id else "/schedules",
                            "service_name": schedule.service_name,
                            "schedule_name": schedule.name,
                            "status": new_status,
                        })
                    except Exception:
                        logger.exception("Failed to notify for schedule %d", schedule.id)

            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Error updating completed schedules")
        finally:
            session.close()

    @staticmethod
    def _next_run(cron_expression: str) -> datetime:
        """Compute the next run time from now."""
        now = datetime.now(timezone.utc)
        cron = croniter(cron_expression, now)
        return cron.get_next(datetime).replace(tzinfo=timezone.utc)
