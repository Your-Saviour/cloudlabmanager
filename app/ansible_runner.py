import asyncio
import hashlib
import json
import re
import uuid
import os
import shutil
import yaml
from datetime import datetime, timezone, timedelta
from models import Job

VAULT_PASS_FILE = "/tmp/.vault_pass.txt"
CLOUDLAB_PATH = "/app/cloudlab"
SERVICES_DIR = os.path.join(CLOUDLAB_PATH, "services")
INVENTORY_FILE = "/inventory/vultr.yml"
ALLOWED_CONFIG_FILES = {"instance.yaml", "config.yaml", "scripts.yaml"}
ALLOWED_FILE_SUBDIRS = {"inputs", "outputs"}
MAX_CONFIG_SIZE = 100 * 1024  # 100KB
MAX_FILE_SIZE = 100 * 1024  # 100KB
MAX_VERSIONS_PER_FILE = 50


def save_config_version(session, service_name: str, filename: str, content: str,
                        user_id: int | None = None, username: str | None = None,
                        change_note: str | None = None, ip_address: str | None = None):
    """Snapshot a config file's content as a new version. Prune old versions beyond MAX_VERSIONS_PER_FILE."""
    from database import ConfigVersion

    # Truncate change_note to DB column limit
    if change_note and len(change_note) > 500:
        change_note = change_note[:500]

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # Determine next version number
    latest = (session.query(ConfigVersion)
              .filter_by(service_name=service_name, filename=filename)
              .order_by(ConfigVersion.version_number.desc())
              .first())
    next_version = (latest.version_number + 1) if latest else 1

    version = ConfigVersion(
        service_name=service_name,
        filename=filename,
        content=content,
        content_hash=content_hash,
        size_bytes=len(content.encode("utf-8")),
        version_number=next_version,
        change_note=change_note,
        created_by_id=user_id,
        created_by_username=username,
        ip_address=ip_address,
    )
    session.add(version)
    session.flush()

    # Prune: delete oldest versions beyond the limit
    count = (session.query(ConfigVersion)
             .filter_by(service_name=service_name, filename=filename)
             .count())
    if count > MAX_VERSIONS_PER_FILE:
        excess = (session.query(ConfigVersion)
                  .filter_by(service_name=service_name, filename=filename)
                  .order_by(ConfigVersion.version_number.asc())
                  .limit(count - MAX_VERSIONS_PER_FILE)
                  .all())
        for old in excess:
            session.delete(old)
        session.flush()

    return version


async def _check_budget_alert(session, cost_data):
    """Check if current costs exceed budget threshold and send alert."""
    from database import AppMetadata
    settings = AppMetadata.get(session, "cost_budget_settings", {})
    if not settings or not settings.get("enabled"):
        return

    threshold = float(settings.get("monthly_threshold", 0))
    if threshold <= 0:
        return

    current_cost = float(cost_data.get("total_monthly_cost", 0))
    if current_cost <= threshold:
        return  # Under budget

    # Check cooldown
    last_alerted = settings.get("last_alerted_at")
    cooldown_hours = int(settings.get("alert_cooldown_hours", 24))
    if last_alerted:
        last_dt = datetime.fromisoformat(last_alerted)
        if datetime.now(timezone.utc) - last_dt < timedelta(hours=cooldown_hours):
            return  # Still in cooldown

    # Dispatch through unified notification system
    from notification_service import notify, EVENT_BUDGET_THRESHOLD_EXCEEDED

    overage = current_cost - threshold
    pct_over = (overage / threshold) * 100

    await notify(EVENT_BUDGET_THRESHOLD_EXCEEDED, {
        "title": f"Budget Alert \u2014 ${current_cost:.2f}/mo exceeds ${threshold:.2f} threshold",
        "body": f"Current cost ${current_cost:.2f} is over budget by ${overage:.2f} ({pct_over:.1f}%). {len(cost_data.get('instances', []))} active instances.",
        "severity": "error",
        "action_url": "/costs",
        "current_cost": current_cost,
        "threshold": threshold,
    })

    # Update last_alerted_at (cooldown tracking)
    settings["last_alerted_at"] = datetime.now(timezone.utc).isoformat()
    AppMetadata.set(session, "cost_budget_settings", settings)
    session.commit()


class AnsibleRunner:
    def __init__(self):
        self.jobs: dict[str, Job] = {}

    def get_service_scripts(self, name: str) -> list[dict]:
        scripts_path = os.path.join(SERVICES_DIR, name, "scripts.yaml")
        if os.path.isfile(scripts_path):
            try:
                with open(scripts_path, "r") as f:
                    data = yaml.safe_load(f)
                if data and "scripts" in data:
                    return data["scripts"]
            except Exception:
                pass
        return [{"name": "deploy", "label": "Deploy", "file": "deploy.sh"}]

    def get_service_output_definitions(self, name: str) -> list[dict]:
        scripts_path = os.path.join(SERVICES_DIR, name, "scripts.yaml")
        if os.path.isfile(scripts_path):
            try:
                with open(scripts_path, "r") as f:
                    data = yaml.safe_load(f)
                if data and "outputs" in data:
                    return data["outputs"]
            except Exception:
                pass
        return []

    def get_services(self) -> list[dict]:
        results = []
        if not os.path.isdir(SERVICES_DIR):
            return results
        for dirname in sorted(os.listdir(SERVICES_DIR)):
            service_path = os.path.join(SERVICES_DIR, dirname)
            deploy_path = os.path.join(service_path, "deploy.sh")
            if os.path.isdir(service_path) and os.path.isfile(deploy_path):
                output_defs = self.get_service_output_definitions(dirname)
                entry = {
                    "name": dirname,
                    "service_dir": f"/services/{dirname}",
                    "scripts": self.get_service_scripts(dirname),
                }
                if output_defs:
                    entry["output_definitions"] = output_defs
                results.append(entry)
        return results

    def get_service(self, name: str) -> dict | None:
        service_path = os.path.join(SERVICES_DIR, name)
        deploy_path = os.path.join(service_path, "deploy.sh")
        if not os.path.isdir(service_path) or not os.path.isfile(deploy_path):
            return None
        return {"name": name, "service_dir": f"/services/{name}"}

    def get_service_configs(self, name: str) -> dict | None:
        service = self.get_service(name)
        if not service:
            return None
        full_dir = os.path.join(SERVICES_DIR, name)
        configs = []
        for fname in sorted(ALLOWED_CONFIG_FILES):
            fpath = os.path.join(full_dir, fname)
            configs.append({"name": fname, "exists": os.path.isfile(fpath)})
        return {"service_dir": service["service_dir"], "configs": configs}

    def read_config_file(self, name: str, filename: str) -> str | None:
        if filename not in ALLOWED_CONFIG_FILES:
            raise ValueError(f"File '{filename}' is not allowed")
        service = self.get_service(name)
        if not service:
            raise FileNotFoundError("Service not found")
        full_path = os.path.join(SERVICES_DIR, name, filename)
        real_path = os.path.realpath(full_path)
        allowed_base = os.path.realpath(SERVICES_DIR)
        if not real_path.startswith(allowed_base + "/"):
            raise ValueError("Path traversal detected")
        if not os.path.isfile(real_path):
            raise FileNotFoundError(f"File '{filename}' not found")
        size = os.path.getsize(real_path)
        if size > MAX_CONFIG_SIZE:
            raise ValueError(f"File too large ({size} bytes)")
        with open(real_path, "r") as f:
            return f.read()

    def write_config_file(self, name: str, filename: str, content: str) -> None:
        if filename not in ALLOWED_CONFIG_FILES:
            raise ValueError(f"File '{filename}' is not allowed")
        service = self.get_service(name)
        if not service:
            raise FileNotFoundError("Service not found")
        full_path = os.path.join(SERVICES_DIR, name, filename)
        real_path = os.path.realpath(full_path)
        allowed_base = os.path.realpath(SERVICES_DIR)
        if not real_path.startswith(allowed_base + "/"):
            raise ValueError("Path traversal detected")
        if len(content.encode("utf-8")) > MAX_CONFIG_SIZE:
            raise ValueError("Content too large")
        yaml.safe_load(content)  # Validate YAML syntax
        if os.path.isfile(real_path):
            shutil.copy2(real_path, real_path + ".backup")
        with open(real_path, "w") as f:
            f.write(content)

    # --- File management for inputs/outputs ---

    def _validate_file_path(self, name: str, subdir: str, filename: str) -> str:
        if subdir not in ALLOWED_FILE_SUBDIRS:
            raise ValueError(f"Subdirectory must be one of: {ALLOWED_FILE_SUBDIRS}")
        service = self.get_service(name)
        if not service:
            raise FileNotFoundError("Service not found")
        full_path = os.path.join(SERVICES_DIR, name, subdir, filename)
        real_path = os.path.realpath(full_path)
        allowed_base = os.path.realpath(os.path.join(SERVICES_DIR, name, subdir))
        if not real_path.startswith(allowed_base + "/") and real_path != allowed_base:
            raise ValueError("Path traversal detected")
        return real_path

    def list_service_files(self, name: str, subdir: str) -> list[dict]:
        if subdir not in ALLOWED_FILE_SUBDIRS:
            raise ValueError(f"Subdirectory must be one of: {ALLOWED_FILE_SUBDIRS}")
        service = self.get_service(name)
        if not service:
            raise FileNotFoundError("Service not found")
        dir_path = os.path.join(SERVICES_DIR, name, subdir)
        if not os.path.isdir(dir_path):
            return []
        files = []
        for fname in sorted(os.listdir(dir_path)):
            fpath = os.path.join(dir_path, fname)
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                files.append({
                    "name": fname,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                })
        return files

    def read_service_file(self, name: str, subdir: str, filename: str) -> str:
        real_path = self._validate_file_path(name, subdir, filename)
        if not os.path.isfile(real_path):
            raise FileNotFoundError(f"File '{filename}' not found")
        size = os.path.getsize(real_path)
        if size > MAX_FILE_SIZE:
            raise ValueError(f"File too large ({size} bytes, max {MAX_FILE_SIZE})")
        with open(real_path, "r") as f:
            return f.read()

    def get_service_file_path(self, name: str, subdir: str, filename: str) -> str:
        real_path = self._validate_file_path(name, subdir, filename)
        if not os.path.isfile(real_path):
            raise FileNotFoundError(f"File '{filename}' not found")
        return real_path

    def write_service_file(self, name: str, subdir: str, filename: str, content: bytes) -> None:
        if subdir not in ALLOWED_FILE_SUBDIRS:
            raise ValueError(f"Subdirectory must be one of: {ALLOWED_FILE_SUBDIRS}")
        service = self.get_service(name)
        if not service:
            raise FileNotFoundError("Service not found")
        dir_path = os.path.join(SERVICES_DIR, name, subdir)
        os.makedirs(dir_path, exist_ok=True)
        full_path = os.path.join(dir_path, filename)
        real_path = os.path.realpath(full_path)
        allowed_base = os.path.realpath(dir_path)
        if not real_path.startswith(allowed_base + "/") and real_path != allowed_base:
            raise ValueError("Path traversal detected")
        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"File too large ({len(content)} bytes, max {MAX_FILE_SIZE})")
        with open(real_path, "wb") as f:
            f.write(content)

    def delete_service_file(self, name: str, subdir: str, filename: str) -> None:
        real_path = self._validate_file_path(name, subdir, filename)
        if not os.path.isfile(real_path):
            raise FileNotFoundError(f"File '{filename}' not found")
        # Create backup before deleting
        shutil.copy2(real_path, real_path + ".backup")
        os.remove(real_path)

    # --- Service config readers ---

    def read_service_instance_config(self, name: str) -> dict | None:
        """Parse a service's instance.yaml and return as dict, or None if missing."""
        path = os.path.join(SERVICES_DIR, name, "instance.yaml")
        real_path = os.path.realpath(path)
        allowed_base = os.path.realpath(SERVICES_DIR)
        if not real_path.startswith(allowed_base + "/"):
            return None
        if not os.path.isfile(real_path):
            return None
        try:
            with open(real_path, "r") as f:
                return yaml.safe_load(f)
        except Exception:
            return None

    def get_all_instance_configs(self) -> dict[str, dict]:
        """Read instance.yaml from every service and return {service_name: parsed_yaml}."""
        configs = {}
        if not os.path.isdir(SERVICES_DIR):
            return configs
        for dirname in sorted(os.listdir(SERVICES_DIR)):
            service_path = os.path.join(SERVICES_DIR, dirname)
            if not os.path.isdir(service_path):
                continue
            instance_path = os.path.join(service_path, "instance.yaml")
            if not os.path.isfile(instance_path):
                continue
            try:
                with open(instance_path, "r") as f:
                    data = yaml.safe_load(f)
                if data:
                    configs[dirname] = data
            except Exception:
                continue
        return configs

    def read_service_config(self, name: str) -> dict | None:
        """Parse a service's config.yaml and return as dict, or None if missing."""
        path = os.path.join(SERVICES_DIR, name, "config.yaml")
        real_path = os.path.realpath(path)
        allowed_base = os.path.realpath(SERVICES_DIR)
        if not real_path.startswith(allowed_base + "/"):
            return None
        if not os.path.isfile(real_path):
            return None
        try:
            with open(real_path, "r") as f:
                return yaml.safe_load(f)
        except Exception:
            return None

    # --- SSH credential resolution ---

    def resolve_ssh_credentials(self, hostname: str) -> dict | None:
        """Scan all service temp_inventory.yaml files to find SSH credentials for a hostname."""
        if not os.path.isdir(SERVICES_DIR):
            return None
        for dirname in os.listdir(SERVICES_DIR):
            outputs_dir = os.path.join(SERVICES_DIR, dirname, "outputs")
            if not os.path.isdir(outputs_dir):
                continue
            # Check top-level temp_inventory.yaml and per-instance subdirectories
            candidates = [os.path.join(outputs_dir, "temp_inventory.yaml")]
            for entry in os.listdir(outputs_dir):
                sub_inv = os.path.join(outputs_dir, entry, "temp_inventory.yaml")
                if os.path.isfile(sub_inv):
                    candidates.append(sub_inv)
            for inv_path in candidates:
                try:
                    with open(inv_path, "r") as f:
                        inv_data = yaml.safe_load(f)
                    hosts = inv_data.get("all", {}).get("hosts", {})
                    if hostname in hosts:
                        info = hosts[hostname]
                        key_file = info.get("ansible_ssh_private_key_file")
                        if key_file and os.path.isfile(key_file):
                            return {
                                "ansible_host": info.get("ansible_host"),
                                "ansible_user": info.get("ansible_user", "root"),
                                "ansible_ssh_private_key_file": key_file,
                                "service": dirname,
                            }
                except Exception:
                    continue
        return None

    # --- Generic inventory action execution ---

    async def run_action(self, action_def: dict, obj_data: dict, type_slug: str,
                         user_id: int | None = None, username: str | None = None,
                         object_id: int | None = None) -> Job:
        """Execute an inventory action (script, playbook, etc.) and return a Job."""
        action_name = action_def["name"]
        action_type = action_def.get("type", "script")
        service_name = obj_data.get("name", type_slug)

        job_id = str(uuid.uuid4())[:8]
        job = Job(
            id=job_id,
            service=service_name,
            action=action_name,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={
                "action_name": action_name,
                "action_type": action_def.get("type", "script"),
                "type_slug": type_slug,
                **(action_def.get("_inputs", {})),
            },
        )
        self.jobs[job_id] = job

        asyncio.create_task(self._run_action_job(job, action_def, obj_data, type_slug, object_id))
        return job

    async def _run_action_job(self, job: Job, action_def: dict, obj_data: dict,
                               type_slug: str, object_id: int | None):
        action_type = action_def.get("type", "script")
        action_name = action_def["name"]
        service_name = obj_data.get("name", "")

        job.output.append(f"--- Running {action_name} ({action_type}) ---")

        # Build env vars from inputs if provided
        run_env = None
        inputs = action_def.get("_inputs", {})
        if inputs:
            run_env = dict(os.environ)
            for iname, value in inputs.items():
                env_key = f"INPUT_{iname.upper()}"
                if isinstance(value, list):
                    run_env[env_key] = ",".join(str(v) for v in value)
                else:
                    run_env[env_key] = str(value)

        # Auto-inject authenticated user's username if not already provided
        if job.username and (not run_env or "INPUT_USERNAME" not in run_env):
            if run_env is None:
                run_env = dict(os.environ)
            run_env["INPUT_USERNAME"] = job.username

        ok = False
        if action_type == "script":
            script_file = action_def.get("script", "deploy.sh")
            script_path = f"/services/{service_name}/{script_file}"
            if os.path.isfile(script_path):
                ok = await self._run_command(job, ["bash", script_path], env=run_env)
            else:
                job.output.append(f"[ERROR: Script not found: {script_path}]")

        elif action_type == "script_stop":
            # Generate inventory then stop instances for this service
            job.output.append("--- Generating inventory ---")
            await self._run_command(job, [
                "ansible-playbook",
                "/init_playbook/generate-inventory.yaml",
                "--vault-password-file", VAULT_PASS_FILE,
            ])
            job.output.append(f"--- Stopping {service_name} instances ---")
            ok = await self._run_command(job, [
                "ansible-playbook",
                "/init_playbook/stop-instances.yaml",
                "--vault-password-file", VAULT_PASS_FILE,
                "-i", "/inventory/vultr.yml",
                "-e", f"service_filter={service_name}",
            ])

        elif action_type == "playbook":
            playbook = action_def.get("playbook", "")
            if not playbook or not os.path.isfile(playbook):
                job.output.append(f"[ERROR: Playbook not found: {playbook}]")
            else:
                cmd = [
                    "ansible-playbook", playbook,
                    "--vault-password-file", VAULT_PASS_FILE,
                ]
                # Apply vars_mapping: substitute {{ field }} with obj_data values
                vars_mapping = action_def.get("vars_mapping", {})
                for var_name, template in vars_mapping.items():
                    value = template
                    for field_name, field_value in obj_data.items():
                        value = value.replace(f"{{{{ {field_name} }}}}", str(field_value))
                    cmd.extend(["-e", f"{var_name}={value}"])
                ok = await self._run_command(job, cmd)

        elif action_type == "dynamic_scripts":
            # Read scripts.yaml from service dir and run the requested script
            script_name = action_def.get("script_name", "deploy")
            scripts = self.get_service_scripts(service_name)
            script_def = next((s for s in scripts if s["name"] == script_name), None)
            if script_def:
                script_file = script_def["file"]
                script_path = f"/services/{service_name}/{script_file}"
                if os.path.isfile(script_path):
                    ok = await self._run_command(job, ["bash", script_path], env=run_env)
                else:
                    job.output.append(f"[ERROR: Script not found: {script_path}]")
            else:
                job.output.append(f"[ERROR: Script '{script_name}' not found in scripts.yaml]")

        else:
            job.output.append(f"[ERROR: Unknown action type: {action_type}]")

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job, object_id=object_id, type_slug=type_slug)
        await self._notify_job(job)

        # Update last_used_at for referenced library files
        library_file_ids = action_def.get("_library_file_ids")
        if library_file_ids:
            try:
                from database import SessionLocal, FileLibraryItem
                with SessionLocal() as sess:
                    sess.query(FileLibraryItem).filter(
                        FileLibraryItem.id.in_(library_file_ids)
                    ).update(
                        {"last_used_at": datetime.now(timezone.utc)},
                        synchronize_session=False
                    )
                    sess.commit()
            except Exception as e:
                print(f"[library] Failed to update last_used_at: {e}")

        # Post-action: keep instances cache and inventory objects in sync
        if ok and type_slug == "server":
            try:
                self._sync_server_inventory(job, action_name, object_id)
            except Exception as e:
                job.output.append(f"[Warning: Could not update inventory: {e}]")

    def _sync_server_inventory(self, job: Job, action_name: str, object_id: int | None):
        """Keep instances cache and inventory objects in sync after server actions."""
        from database import SessionLocal, AppMetadata, InventoryObject
        import json as _json

        session = SessionLocal()
        try:
            if action_name == "destroy" and object_id:
                # Remove destroyed server from cache and delete the object
                linked = session.query(InventoryObject).get(object_id)
                if linked:
                    linked_data = _json.loads(linked.data)
                    hostname = linked_data.get("hostname", "")

                    cache = AppMetadata.get(session, "instances_cache") or {}
                    hosts = cache.get("all", {}).get("hosts", {})
                    children = cache.get("all", {}).get("children", {})

                    if hostname and hostname in hosts:
                        del hosts[hostname]
                        for group in children.values():
                            group.get("hosts", {}).pop(hostname, None)
                        AppMetadata.set(session, "instances_cache", cache)
                        AppMetadata.set(session, "instances_cache_time",
                                        datetime.now(timezone.utc).isoformat())

                    session.delete(linked)
                    session.commit()
                    job.output.append("[Server removed from inventory]")

            elif action_name == "refresh":
                # Re-read inventory file into cache, then re-sync all server objects
                if os.path.isfile(INVENTORY_FILE):
                    with open(INVENTORY_FILE, "r") as f:
                        inv_data = yaml.safe_load(f)
                    AppMetadata.set(session, "instances_cache", inv_data)
                    AppMetadata.set(session, "instances_cache_time",
                                    datetime.now(timezone.utc).isoformat())
                    session.commit()
                    job.output.append("[Inventory cache updated]")

                from inventory_sync import run_sync_for_source
                run_sync_for_source("vultr_inventory")
                job.output.append("[Inventory objects synced]")
                run_sync_for_source("ssh_credential_sync")
                job.output.append("[SSH credentials synced]")
        finally:
            session.close()

    # --- Deployment / job methods ---

    async def run_script(self, name: str, script_name: str, inputs: dict,
                         user_id: int | None = None, username: str | None = None,
                         temp_dir: str | None = None,
                         library_file_ids: list[int] | None = None) -> Job:
        service = self.get_service(name)
        if not service:
            raise FileNotFoundError(f"Service '{name}' not found")

        scripts = self.get_service_scripts(name)
        script_def = next((s for s in scripts if s["name"] == script_name), None)
        if not script_def:
            raise ValueError(f"Script '{script_name}' not found for service '{name}'")

        # Validate required inputs
        for input_def in script_def.get("inputs", []):
            if input_def.get("required") and input_def["name"] not in inputs:
                raise ValueError(f"Missing required input: {input_def['name']}")

        # Resolve ssh_key_select inputs: convert user IDs to actual SSH public keys
        ssh_key_inputs = {
            inp["name"] for inp in script_def.get("inputs", [])
            if inp.get("type") == "ssh_key_select"
        }
        if ssh_key_inputs:
            from database import SessionLocal, User as DBUser
            with SessionLocal() as db:
                for iname in ssh_key_inputs:
                    user_ids = inputs.get(iname)
                    if not user_ids or not isinstance(user_ids, list):
                        continue
                    int_ids = [int(uid) for uid in user_ids]
                    users = db.query(DBUser).filter(
                        DBUser.id.in_(int_ids),
                        DBUser.ssh_public_key != None,
                    ).all()
                    keys = [u.ssh_public_key for u in users if u.ssh_public_key]
                    inputs[iname] = keys

        # Build env vars from inputs (includes both user-provided and backend-injected values)
        env = dict(os.environ)
        for iname, value in inputs.items():
            env_key = f"INPUT_{iname.upper()}"
            if isinstance(value, list):
                env[env_key] = ",".join(str(v) for v in value)
            else:
                env[env_key] = str(value)

        # Auto-inject authenticated user's username if not already provided
        if username and "INPUT_USERNAME" not in env:
            env["INPUT_USERNAME"] = username

        script_file = script_def["file"]
        full_path = os.path.join(SERVICES_DIR, name, script_file)
        real_path = os.path.realpath(full_path)
        allowed_base = os.path.realpath(os.path.join(SERVICES_DIR, name))
        if not real_path.startswith(allowed_base + "/"):
            raise ValueError("Path traversal detected in script file")
        if not os.path.isfile(real_path):
            raise FileNotFoundError(f"Script file '{script_file}' not found")
        script_path = f"/services/{name}/{script_file}"

        job_id = str(uuid.uuid4())[:8]
        job = Job(
            id=job_id,
            service=name,
            action="script",
            script=script_name,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={"script": script_name, **inputs},
        )
        self.jobs[job_id] = job

        asyncio.create_task(self._run_script_job(job, script_path, env, temp_dir=temp_dir,
                                                  library_file_ids=library_file_ids))
        return job

    async def _run_script_job(self, job: Job, script_path: str, env: dict,
                               temp_dir: str | None = None,
                               library_file_ids: list[int] | None = None):
        job.output.append(f"--- Running {job.script} for {job.service} ---")
        ok = await self._run_command(job, ["bash", script_path], env=env)

        if ok:
            self._sync_service_outputs(job, job.service)
            try:
                from inventory_sync import run_sync_for_source
                run_sync_for_source("ssh_credential_sync")
                job.output.append("[SSH credentials synced]")
            except Exception as e:
                job.output.append(f"[Warning: SSH credential sync failed: {e}]")

        # Update last_used_at for referenced library files
        if library_file_ids:
            try:
                from database import SessionLocal, FileLibraryItem
                with SessionLocal() as session:
                    session.query(FileLibraryItem).filter(
                        FileLibraryItem.id.in_(library_file_ids)
                    ).update({"last_used_at": datetime.now(timezone.utc)}, synchronize_session=False)
                    session.commit()
            except Exception as e:
                print(f"[library] Failed to update last_used_at: {e}")

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        await self._notify_job(job)

        # Clean up temp upload directory if present
        if temp_dir and os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"[cleanup] Failed to remove temp dir {temp_dir}: {e}")

    async def deploy_service(self, name: str,
                             user_id: int | None = None, username: str | None = None) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            id=job_id,
            service=name,
            action="deploy",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={},
        )
        self.jobs[job_id] = job

        asyncio.create_task(self._run_deploy(job))
        return job

    async def stop_service(self, name: str,
                           user_id: int | None = None, username: str | None = None) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            id=job_id,
            service=name,
            action="stop",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={},
        )
        self.jobs[job_id] = job

        asyncio.create_task(self._run_stop(job))
        return job

    async def stop_all(self, user_id: int | None = None, username: str | None = None) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            id=job_id,
            service="all",
            action="stop_all",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={},
        )
        self.jobs[job_id] = job

        asyncio.create_task(self._run_stop_all(job))
        return job

    async def bulk_stop(self, service_names: list[str],
                        user_id: int | None = None, username: str | None = None) -> Job:
        parent_id = str(uuid.uuid4())[:8]
        parent = Job(
            id=parent_id,
            service=f"bulk ({len(service_names)} services)",
            action="bulk_stop",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={"services": service_names},
        )
        self.jobs[parent_id] = parent
        asyncio.create_task(self._run_bulk_stop(parent, service_names))
        return parent

    async def _run_bulk_stop(self, parent: Job, service_names: list[str]):
        parent.output.append(f"--- Bulk stop: {len(service_names)} services ---")
        child_jobs = []
        for name in service_names:
            parent.output.append(f"[Starting stop for {name}]")
            child = await self.stop_service(name, user_id=parent.user_id, username=parent.username)
            child.parent_job_id = parent.id
            child_jobs.append((name, child))

        # Wait for all children to complete
        for name, child in child_jobs:
            while child.status == "running":
                await asyncio.sleep(1)
            parent.output.append(f"[{name}] finished: {child.status}")

        failed = [name for name, child in child_jobs if child.status != "completed"]
        if failed:
            parent.output.append(f"[Failed: {', '.join(failed)}]")
            parent.status = "failed" if len(failed) == len(child_jobs) else "completed"
        else:
            parent.status = "completed"
        parent.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(parent)
        await self._notify_job(parent)
        await self._notify_bulk(parent, child_jobs, "stop")

    async def bulk_deploy(self, service_names: list[str],
                          user_id: int | None = None, username: str | None = None) -> Job:
        parent_id = str(uuid.uuid4())[:8]
        parent = Job(
            id=parent_id,
            service=f"bulk ({len(service_names)} services)",
            action="bulk_deploy",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={"services": service_names},
        )
        self.jobs[parent_id] = parent
        asyncio.create_task(self._run_bulk_deploy(parent, service_names))
        return parent

    async def _run_bulk_deploy(self, parent: Job, service_names: list[str]):
        parent.output.append(f"--- Bulk deploy: {len(service_names)} services ---")
        child_jobs = []
        for name in service_names:
            parent.output.append(f"[Starting deploy for {name}]")
            child = await self.deploy_service(name, user_id=parent.user_id, username=parent.username)
            child.parent_job_id = parent.id
            child_jobs.append((name, child))

        # Wait for all children to complete
        for name, child in child_jobs:
            while child.status == "running":
                await asyncio.sleep(1)
            parent.output.append(f"[{name}] finished: {child.status}")

        failed = [name for name, child in child_jobs if child.status != "completed"]
        if failed:
            parent.output.append(f"[Failed: {', '.join(failed)}]")
            parent.status = "failed" if len(failed) == len(child_jobs) else "completed"
        else:
            parent.status = "completed"
        parent.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(parent)
        await self._notify_job(parent)
        await self._notify_bulk(parent, child_jobs, "deploy")

    async def stop_instance(self, label: str, region: str,
                            user_id: int | None = None, username: str | None = None) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            id=job_id,
            service=label,
            action="destroy_instance",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={"label": label, "region": region},
        )
        self.jobs[job_id] = job

        asyncio.create_task(self._run_stop_instance(job, label, region))
        return job

    async def refresh_instances(self, user_id: int | None = None, username: str | None = None) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            id=job_id,
            service="inventory",
            action="refresh",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={},
        )
        self.jobs[job_id] = job

        asyncio.create_task(self._run_refresh(job))
        return job

    async def _run_command(self, job: Job, args: list[str], cwd: str | None = None, env: dict | None = None):
        job.output.append(f"$ {' '.join(args)}")
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
                env=env,
            )
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                job.output.append(decoded)
                if not job.deployment_id:
                    m = re.search(r"DEPLOYMENT_ID=([\w-]+)", decoded)
                    if m:
                        job.deployment_id = m.group(1)

            await process.wait()
            if process.returncode != 0:
                job.output.append(f"[EXIT CODE: {process.returncode}]")
                return False
            return True
        except Exception as e:
            job.output.append(f"[ERROR: {str(e)}]")
            return False

    async def _run_deploy(self, job: Job):
        name = job.service
        service = self.get_service(name)
        if not service:
            job.output.append(f"[ERROR: Service '{name}' not found]")
            job.status = "failed"
            job.finished_at = datetime.now(timezone.utc).isoformat()
            self._persist_job(job)
            await self._notify_job(job)
            return

        script_path = f"/services/{name}/deploy.sh"
        job.output.append(f"--- Running deploy.sh for {name} ---")
        ok = await self._run_command(job, ["bash", script_path])

        if ok:
            self._sync_service_outputs(job, name)
            try:
                from inventory_sync import run_sync_for_source
                run_sync_for_source("ssh_credential_sync")
                job.output.append("[SSH credentials synced]")
            except Exception as e:
                job.output.append(f"[Warning: SSH credential sync failed: {e}]")

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        await self._notify_job(job)

    async def _run_stop(self, job: Job):
        name = job.service
        service = self.get_service(name)
        if not service:
            job.output.append(f"[ERROR: Service '{name}' not found]")
            job.status = "failed"
            job.finished_at = datetime.now(timezone.utc).isoformat()
            self._persist_job(job)
            await self._notify_job(job)
            return

        # Generate inventory then stop instances matching this service
        job.output.append("--- Generating inventory ---")
        await self._run_command(job, [
            "ansible-playbook",
            "/init_playbook/generate-inventory.yaml",
            "--vault-password-file", VAULT_PASS_FILE,
        ])

        job.output.append(f"--- Stopping {name} instances ---")
        ok = await self._run_command(job, [
            "ansible-playbook",
            "/init_playbook/stop-instances.yaml",
            "--vault-password-file", VAULT_PASS_FILE,
            "-i", "/inventory/vultr.yml",
            "-e", f"service_filter={name}",
        ])

        if ok:
            self._refresh_cache_after_stop(job)

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        await self._notify_job(job)

    async def _run_stop_all(self, job: Job):
        job.output.append("--- Generating inventory ---")
        await self._run_command(job, [
            "ansible-playbook",
            "/init_playbook/generate-inventory.yaml",
            "--vault-password-file", VAULT_PASS_FILE,
        ])

        job.output.append("--- Stopping all instances ---")
        ok = await self._run_command(job, [
            "ansible-playbook",
            "/init_playbook/stop-instances.yaml",
            "--vault-password-file", VAULT_PASS_FILE,
            "-i", "/inventory/vultr.yml",
        ])

        if ok:
            self._refresh_cache_after_stop(job)

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        await self._notify_job(job)

    def _refresh_cache_after_stop(self, job: Job):
        """Re-generate inventory from Vultr API and sync DB cache/objects.

        Called after stop operations so destroyed instances are removed from
        the dashboard, health checks, and inventory.  Only touches DB records
        — does NOT delete certificate or key files on disk.
        """
        try:
            from database import SessionLocal, AppMetadata
            import subprocess

            # Re-generate the inventory file from live Vultr state
            job.output.append("[Refreshing inventory after stop]")
            result = subprocess.run(
                [
                    "ansible-playbook",
                    "/init_playbook/generate-inventory.yaml",
                    "--vault-password-file", VAULT_PASS_FILE,
                ],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                job.output.append(f"[Warning: inventory refresh failed: {result.stderr[-300:] if result.stderr else 'unknown'}]")
                return

            # Read the freshly generated inventory into the DB cache
            if os.path.isfile(INVENTORY_FILE):
                with open(INVENTORY_FILE, "r") as f:
                    inv_data = yaml.safe_load(f)
                session = SessionLocal()
                try:
                    AppMetadata.set(session, "instances_cache", inv_data)
                    AppMetadata.set(session, "instances_cache_time",
                                    datetime.now(timezone.utc).isoformat())
                    session.commit()
                    job.output.append("[Inventory cache updated]")
                finally:
                    session.close()

            # Sync inventory objects (removes stale servers + orphaned passwords)
            from inventory_sync import run_sync_for_source
            run_sync_for_source("vultr_inventory")
            job.output.append("[Inventory objects synced]")
            run_sync_for_source("ssh_credential_sync")
            job.output.append("[SSH credentials synced]")
        except Exception as e:
            job.output.append(f"[Warning: post-stop cleanup failed: {e}]")

    async def _run_refresh(self, job: Job):
        job.output.append("--- Generating inventory ---")
        ok = await self._run_command(job, [
            "ansible-playbook",
            "/init_playbook/generate-inventory.yaml",
            "--vault-password-file", VAULT_PASS_FILE,
        ])

        if ok:
            # Try to parse the generated inventory and store instances
            if os.path.isfile(INVENTORY_FILE):
                try:
                    with open(INVENTORY_FILE, "r") as f:
                        inv_data = yaml.safe_load(f)
                    from database import SessionLocal, AppMetadata
                    session = SessionLocal()
                    try:
                        AppMetadata.set(session, "instances_cache", inv_data)
                        AppMetadata.set(session, "instances_cache_time", datetime.now(timezone.utc).isoformat())

                        # Cache plan pricing data if available
                        plans_file = "/outputs/instance_plans_output.json"
                        if os.path.isfile(plans_file):
                            with open(plans_file, "r") as f:
                                plans_data = json.load(f)
                            AppMetadata.set(session, "plans_cache", plans_data)
                            job.output.append("[Plan pricing cached]")

                        session.commit()
                        job.output.append("[Inventory cached successfully]")
                    finally:
                        session.close()

                    from inventory_sync import run_sync_for_source
                    run_sync_for_source("vultr_inventory")
                    job.output.append("[Inventory objects synced]")
                    run_sync_for_source("ssh_credential_sync")
                    job.output.append("[SSH credentials synced]")
                except Exception as e:
                    job.output.append(f"[Warning: Could not cache inventory: {e}]")

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        await self._notify_job(job)

    async def refresh_costs(self, user_id: int | None = None, username: str | None = None) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            id=job_id,
            service="costs",
            action="refresh",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={},
        )
        self.jobs[job_id] = job

        asyncio.create_task(self._run_refresh_costs(job))
        return job

    async def _run_refresh_costs(self, job: Job):
        job.output.append("--- Fetching cost data from Vultr ---")
        ok = await self._run_command(job, [
            "ansible-playbook",
            "/init_playbook/cost-info.yaml",
            "--vault-password-file", VAULT_PASS_FILE,
        ])

        if ok:
            cost_report_file = "/outputs/cost_report.json"
            if os.path.isfile(cost_report_file):
                try:
                    with open(cost_report_file, "r") as f:
                        cost_data = json.load(f)
                    from database import SessionLocal, AppMetadata
                    session = SessionLocal()
                    try:
                        AppMetadata.set(session, "cost_cache", cost_data)
                        AppMetadata.set(session, "cost_cache_time", datetime.now(timezone.utc).isoformat())

                        # Also cache plan pricing data
                        plans_file = "/outputs/instance_plans_output.json"
                        if os.path.isfile(plans_file):
                            with open(plans_file, "r") as f:
                                plans_data = json.load(f)
                            AppMetadata.set(session, "plans_cache", plans_data)
                            AppMetadata.set(session, "plans_cache_time", datetime.now(timezone.utc).isoformat())

                        # Insert cost snapshot for historical tracking
                        from database import CostSnapshot
                        snapshot = CostSnapshot(
                            total_monthly_cost=str(cost_data.get("total_monthly_cost", 0)),
                            instance_count=len(cost_data.get("instances", [])),
                            snapshot_data=json.dumps(cost_data),
                            source="playbook",
                        )
                        session.add(snapshot)

                        # Clean up old snapshots beyond retention period
                        self._cleanup_old_snapshots(session)

                        session.commit()
                        job.output.append("[Cost data cached successfully]")
                        job.output.append("[Cost snapshot saved]")

                        # Check budget threshold and send alert if exceeded
                        try:
                            await _check_budget_alert(session, cost_data)
                        except Exception as e:
                            job.output.append(f"[Warning: Budget alert check failed: {e}]")
                    finally:
                        session.close()
                except Exception as e:
                    job.output.append(f"[Warning: Could not cache cost data: {e}]")

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        await self._notify_job(job)

    def _cleanup_old_snapshots(self, session, retention_days=365):
        """Delete cost snapshots older than retention period."""
        from database import CostSnapshot
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        session.query(CostSnapshot).filter(CostSnapshot.captured_at < cutoff).delete()

    async def _run_stop_instance(self, job: Job, label: str, region: str):
        job.output.append(f"--- Destroying instance: {label} ({region}) ---")
        ok = await self._run_command(job, [
            "ansible-playbook",
            "/init_playbook/stop-single-instance.yaml",
            "--vault-password-file", VAULT_PASS_FILE,
            "-e", f"instance_label={label}",
            "-e", f"instance_region={region}",
        ])

        if ok:
            # Remove the destroyed instance from the local cache immediately.
            try:
                from database import SessionLocal, AppMetadata
                session = SessionLocal()
                try:
                    cache = AppMetadata.get(session, "instances_cache") or {}
                    hosts = cache.get("all", {}).get("hosts", {})
                    children = cache.get("all", {}).get("children", {})

                    removed_hostname = None
                    for hostname, info in list(hosts.items()):
                        if info.get("vultr_label") == label and info.get("vultr_region") == region:
                            removed_hostname = hostname
                            del hosts[hostname]
                            break

                    if removed_hostname:
                        for group in children.values():
                            group_hosts = group.get("hosts", {})
                            group_hosts.pop(removed_hostname, None)

                    AppMetadata.set(session, "instances_cache", cache)
                    AppMetadata.set(session, "instances_cache_time", datetime.now(timezone.utc).isoformat())
                    session.commit()
                    job.output.append("[Instance removed from cache]")
                finally:
                    session.close()

                from inventory_sync import run_sync_for_source
                run_sync_for_source("vultr_inventory")
                job.output.append("[Inventory objects synced]")
                run_sync_for_source("ssh_credential_sync")
                job.output.append("[SSH credentials synced]")
            except Exception as e:
                job.output.append(f"[Warning: Could not update cache: {e}]")

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        await self._notify_job(job)

    def _sync_service_outputs(self, job: Job, service_name: str):
        """Read service outputs and sync credentials to inventory after a successful deploy."""
        try:
            from service_outputs import get_service_outputs, sync_credentials_to_inventory
            outputs = get_service_outputs(service_name)
            if outputs:
                sync_credentials_to_inventory(service_name, outputs)
                job.output.append(f"[Service outputs synced for {service_name}]")
        except Exception as e:
            job.output.append(f"[Warning: Could not sync service outputs: {e}]")

    async def _notify_bulk(self, parent: Job, child_jobs: list, operation: str):
        """Fire a bulk-specific notification after a bulk stop/deploy completes."""
        from notification_service import notify, EVENT_BULK_COMPLETED
        try:
            services = parent.inputs.get("services", [])
            failed_count = sum(1 for _, child in child_jobs if child.status != "completed")
            succeeded_count = len(child_jobs) - failed_count
            await notify(EVENT_BULK_COMPLETED, {
                "title": f"Bulk {operation} {parent.status}: {len(services)} services",
                "body": f"{succeeded_count} succeeded, {failed_count} failed.",
                "severity": "success" if parent.status == "completed" else "warning",
                "action_url": f"/jobs/{parent.id}",
                "status": parent.status,
                "operation": operation,
                "service_count": len(services),
                "job_id": parent.id,
            })
        except Exception:
            print(f"[notification] Failed to notify for bulk {operation} {parent.id}")

    async def _notify_job(self, job: Job):
        """Fire a notification for a completed/failed job."""
        from notification_service import notify, EVENT_JOB_COMPLETED, EVENT_JOB_FAILED

        event_type = EVENT_JOB_COMPLETED if job.status == "completed" else EVENT_JOB_FAILED
        severity = "success" if job.status == "completed" else "error"
        action_label = job.script or job.action

        try:
            await notify(event_type, {
                "title": f"Job {job.status}: {job.service} / {action_label}",
                "body": f"Job {job.id} ({action_label}) on {job.service} has {job.status}.",
                "severity": severity,
                "action_url": f"/jobs/{job.id}",
                "service_name": job.service,
                "status": job.status,
                "job_id": job.id,
            })
        except Exception as e:
            print(f"[notification] Failed to notify for job {job.id}: {e}")

    # --- Snapshot methods ---

    async def sync_snapshots(self, user_id: int | None = None, username: str | None = None) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            id=job_id,
            service="snapshots",
            action="sync",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={},
        )
        self.jobs[job_id] = job
        asyncio.create_task(self._run_sync_snapshots(job))
        return job

    async def _run_sync_snapshots(self, job: Job):
        job.output.append("--- Syncing snapshots from Vultr ---")
        ok = await self._run_command(job, [
            "ansible-playbook",
            "/init_playbook/snapshot-list.yaml",
            "--vault-password-file", VAULT_PASS_FILE,
        ])

        if ok:
            snapshots_file = "/outputs/snapshots.json"
            if os.path.isfile(snapshots_file):
                try:
                    with open(snapshots_file, "r") as f:
                        vultr_snapshots = json.load(f)

                    from database import SessionLocal, AppMetadata, Snapshot
                    session = SessionLocal()
                    try:
                        # Cache raw list for fast reads
                        AppMetadata.set(session, "snapshots_cache", vultr_snapshots)
                        AppMetadata.set(session, "snapshots_cache_time",
                                        datetime.now(timezone.utc).isoformat())

                        # Upsert each snapshot into DB
                        vultr_ids_seen = set()
                        for snap_data in vultr_snapshots:
                            vultr_id = snap_data.get("id", "")
                            if not vultr_id:
                                continue
                            vultr_ids_seen.add(vultr_id)

                            existing = session.query(Snapshot).filter_by(
                                vultr_snapshot_id=vultr_id).first()
                            if existing:
                                existing.status = snap_data.get("status", existing.status)
                                existing.size_gb = snap_data.get("size", existing.size_gb)
                                existing.description = snap_data.get("description", existing.description)
                                existing.os_id = snap_data.get("os_id", existing.os_id)
                                existing.app_id = snap_data.get("app_id", existing.app_id)
                                existing.vultr_created_at = snap_data.get("date_created", existing.vultr_created_at)
                            else:
                                new_snap = Snapshot(
                                    vultr_snapshot_id=vultr_id,
                                    description=snap_data.get("description"),
                                    status=snap_data.get("status", "complete"),
                                    size_gb=snap_data.get("size"),
                                    os_id=snap_data.get("os_id"),
                                    app_id=snap_data.get("app_id"),
                                    vultr_created_at=snap_data.get("date_created"),
                                )
                                session.add(new_snap)

                        # Orphan cleanup: remove DB rows for snapshots no longer in Vultr
                        all_db_snaps = session.query(Snapshot).all()
                        for db_snap in all_db_snaps:
                            if db_snap.vultr_snapshot_id not in vultr_ids_seen:
                                session.delete(db_snap)

                        session.commit()
                        job.output.append(f"[Synced {len(vultr_ids_seen)} snapshots]")
                    finally:
                        session.close()
                except Exception as e:
                    job.output.append(f"[Warning: Could not sync snapshot data: {e}]")

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        await self._notify_job(job)

    async def create_snapshot(self, instance_vultr_id: str, description: str | None = None,
                              user_id: int | None = None, username: str | None = None) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            id=job_id,
            service="snapshots",
            action="create",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={"instance_vultr_id": instance_vultr_id, "description": description or ""},
        )
        self.jobs[job_id] = job
        asyncio.create_task(self._run_create_snapshot(job, instance_vultr_id,
                                                       description or "CloudLab snapshot",
                                                       user_id, username))
        return job

    async def _run_create_snapshot(self, job: Job, instance_vultr_id: str, description: str,
                                    user_id: int | None, username: str | None):
        job.output.append(f"--- Creating snapshot of instance {instance_vultr_id} ---")
        ok = await self._run_command(job, [
            "ansible-playbook",
            "/init_playbook/snapshot-create.yaml",
            "--vault-password-file", VAULT_PASS_FILE,
            "-e", f"instance_id={instance_vultr_id}",
            "-e", f"description={description}",
        ])

        if ok:
            result_file = "/outputs/snapshot_create_result.json"
            if os.path.isfile(result_file):
                try:
                    with open(result_file, "r") as f:
                        snap_data = json.load(f)

                    from database import SessionLocal, Snapshot, AppMetadata
                    session = SessionLocal()
                    try:
                        # Look up instance label from cache
                        instance_label = None
                        instances_cache = AppMetadata.get(session, "instances_cache") or {}
                        hosts = instances_cache.get("all", {}).get("hosts", {})
                        for _hostname, info in hosts.items():
                            if info.get("vultr_id") == instance_vultr_id:
                                instance_label = info.get("vultr_label", _hostname)
                                break

                        new_snap = Snapshot(
                            vultr_snapshot_id=snap_data.get("id", ""),
                            instance_vultr_id=instance_vultr_id,
                            instance_label=instance_label,
                            description=snap_data.get("description", description),
                            status=snap_data.get("status", "pending"),
                            size_gb=snap_data.get("size"),
                            os_id=snap_data.get("os_id"),
                            app_id=snap_data.get("app_id"),
                            vultr_created_at=snap_data.get("date_created"),
                            created_by=user_id,
                            created_by_username=username,
                        )
                        session.add(new_snap)
                        session.commit()
                        job.output.append(f"[Snapshot created: {snap_data.get('id', 'unknown')}]")
                    finally:
                        session.close()
                except Exception as e:
                    job.output.append(f"[Warning: Could not save snapshot record: {e}]")

            # Send notification
            from notification_service import notify, EVENT_SNAPSHOT_CREATED
            try:
                await notify(EVENT_SNAPSHOT_CREATED, {
                    "title": f"Snapshot created for instance {instance_vultr_id}",
                    "body": f"Snapshot '{description}' created successfully.",
                    "severity": "success",
                    "action_url": "/snapshots",
                    "service_name": "snapshots",
                    "status": "completed",
                    "job_id": job.id,
                })
            except Exception:
                pass

            # Trigger a sync after a brief delay to pick up final status
            await asyncio.sleep(5)
            try:
                await self.sync_snapshots()
            except Exception:
                pass

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        await self._notify_job(job)

    async def delete_snapshot(self, vultr_snapshot_id: str,
                              user_id: int | None = None, username: str | None = None) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            id=job_id,
            service="snapshots",
            action="delete",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={"vultr_snapshot_id": vultr_snapshot_id},
        )
        self.jobs[job_id] = job
        asyncio.create_task(self._run_delete_snapshot(job, vultr_snapshot_id, user_id, username))
        return job

    async def _run_delete_snapshot(self, job: Job, vultr_snapshot_id: str,
                                    user_id: int | None, username: str | None):
        job.output.append(f"--- Deleting snapshot {vultr_snapshot_id} ---")
        ok = await self._run_command(job, [
            "ansible-playbook",
            "/init_playbook/snapshot-delete.yaml",
            "--vault-password-file", VAULT_PASS_FILE,
            "-e", f"snapshot_id={vultr_snapshot_id}",
        ])

        if ok:
            # Remove from DB
            from database import SessionLocal, Snapshot
            session = SessionLocal()
            try:
                snap = session.query(Snapshot).filter_by(
                    vultr_snapshot_id=vultr_snapshot_id).first()
                if snap:
                    session.delete(snap)
                    session.commit()
                    job.output.append(f"[Snapshot {vultr_snapshot_id} removed from DB]")
            finally:
                session.close()

            # Send notification
            from notification_service import notify, EVENT_SNAPSHOT_DELETED
            try:
                await notify(EVENT_SNAPSHOT_DELETED, {
                    "title": f"Snapshot {vultr_snapshot_id} deleted",
                    "body": f"Snapshot {vultr_snapshot_id} has been deleted.",
                    "severity": "info",
                    "action_url": "/snapshots",
                    "service_name": "snapshots",
                    "status": "completed",
                    "job_id": job.id,
                })
            except Exception:
                pass

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        await self._notify_job(job)

    async def restore_snapshot(self, snapshot_vultr_id: str, label: str, hostname: str,
                               plan: str, region: str, description: str = "",
                               user_id: int | None = None, username: str | None = None) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(
            id=job_id,
            service="snapshots",
            action="restore",
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            username=username,
            inputs={
                "snapshot_vultr_id": snapshot_vultr_id,
                "label": label,
                "hostname": hostname,
                "plan": plan,
                "region": region,
            },
        )
        self.jobs[job_id] = job
        asyncio.create_task(self._run_restore_snapshot(
            job, snapshot_vultr_id, label, hostname, plan, region, description))
        return job

    async def _run_restore_snapshot(self, job: Job, snapshot_vultr_id: str,
                                     label: str, hostname: str, plan: str, region: str,
                                     description: str):
        job.output.append(f"--- Restoring snapshot {snapshot_vultr_id} to new instance ---")
        ok = await self._run_command(job, [
            "ansible-playbook",
            "/init_playbook/snapshot-restore.yaml",
            "--vault-password-file", VAULT_PASS_FILE,
            "-e", f"snapshot_id={snapshot_vultr_id}",
            "-e", f"instance_label={label}",
            "-e", f"instance_hostname={hostname}",
            "-e", f"instance_plan={plan}",
            "-e", f"instance_region={region}",
        ])

        if ok:
            # Read the result file for instance details
            result_file = "/outputs/snapshot_restore_result.json"
            if os.path.isfile(result_file):
                try:
                    with open(result_file, "r") as f:
                        instance_data = json.load(f)
                    job.output.append(
                        f"[Instance created: {instance_data.get('id', 'unknown')} "
                        f"IP: {instance_data.get('main_ip', 'unknown')}]")
                except Exception as e:
                    job.output.append(f"[Warning: Could not read restore result: {e}]")

            # Refresh instances to pick up the new VM
            try:
                await self.refresh_instances()
            except Exception:
                pass

            # Send notification
            from notification_service import notify, EVENT_SNAPSHOT_RESTORED
            try:
                await notify(EVENT_SNAPSHOT_RESTORED, {
                    "title": f"Snapshot restored: {label}",
                    "body": f"Instance '{label}' created from snapshot '{description}'.",
                    "severity": "success",
                    "action_url": "/snapshots",
                    "service_name": "snapshots",
                    "status": "completed",
                    "job_id": job.id,
                })
            except Exception:
                pass
        else:
            from notification_service import notify, EVENT_SNAPSHOT_RESTORED
            try:
                await notify(EVENT_SNAPSHOT_RESTORED, {
                    "title": f"Snapshot restore failed: {label}",
                    "body": f"Failed to create instance '{label}' from snapshot.",
                    "severity": "error",
                    "action_url": "/snapshots",
                    "service_name": "snapshots",
                    "status": "failed",
                    "job_id": job.id,
                })
            except Exception:
                pass

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)
        await self._notify_job(job)

    def _persist_job(self, job: Job, object_id: int | None = None, type_slug: str | None = None):
        from database import SessionLocal, JobRecord
        session = SessionLocal()
        try:
            existing = session.query(JobRecord).filter_by(id=job.id).first()
            if existing:
                existing.status = job.status
                existing.finished_at = job.finished_at
                existing.output = json.dumps(job.output)
                existing.deployment_id = job.deployment_id
                existing.inputs = json.dumps(job.inputs) if job.inputs else None
                existing.parent_job_id = job.parent_job_id
                if object_id is not None:
                    existing.object_id = object_id
                if type_slug is not None:
                    existing.type_slug = type_slug
                if job.schedule_id is not None:
                    existing.schedule_id = job.schedule_id
                if job.webhook_id is not None:
                    existing.webhook_id = job.webhook_id
            else:
                record = JobRecord(
                    id=job.id,
                    service=job.service,
                    action=job.action,
                    script=job.script,
                    status=job.status,
                    started_at=job.started_at,
                    finished_at=job.finished_at,
                    output=json.dumps(job.output),
                    deployment_id=job.deployment_id,
                    user_id=job.user_id,
                    username=job.username,
                    object_id=object_id,
                    type_slug=type_slug,
                    schedule_id=job.schedule_id,
                    webhook_id=job.webhook_id,
                    inputs=json.dumps(job.inputs) if job.inputs else None,
                    parent_job_id=job.parent_job_id,
                )
                session.add(record)
            session.commit()
        except Exception as e:
            session.rollback()
            print(f"Failed to persist job {job.id}: {e}")
        finally:
            session.close()
