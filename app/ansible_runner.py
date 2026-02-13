import asyncio
import hashlib
import json
import re
import uuid
import os
import shutil
import yaml
from datetime import datetime, timezone
from models import Job

VAULT_PASS_FILE = "/tmp/.vault_pass.txt"
CLOUDLAB_PATH = "/app/cloudlab"
SERVICES_DIR = os.path.join(CLOUDLAB_PATH, "services")
INVENTORY_FILE = "/inventory/vultr.yml"
ALLOWED_CONFIG_FILES = {"instance.yaml", "config.yaml", "scripts.yaml", "outputs.yaml"}
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

    def get_services(self) -> list[dict]:
        results = []
        if not os.path.isdir(SERVICES_DIR):
            return results
        for dirname in sorted(os.listdir(SERVICES_DIR)):
            service_path = os.path.join(SERVICES_DIR, dirname)
            deploy_path = os.path.join(service_path, "deploy.sh")
            if os.path.isdir(service_path) and os.path.isfile(deploy_path):
                results.append({
                    "name": dirname,
                    "service_dir": f"/services/{dirname}",
                    "scripts": self.get_service_scripts(dirname),
                })
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

    # --- SSH credential resolution ---

    def resolve_ssh_credentials(self, hostname: str) -> dict | None:
        """Scan all service temp_inventory.yaml files to find SSH credentials for a hostname."""
        if not os.path.isdir(SERVICES_DIR):
            return None
        for dirname in os.listdir(SERVICES_DIR):
            inv_path = os.path.join(SERVICES_DIR, dirname, "outputs", "temp_inventory.yaml")
            if not os.path.isfile(inv_path):
                continue
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
        finally:
            session.close()

    # --- Deployment / job methods ---

    async def run_script(self, name: str, script_name: str, inputs: dict,
                         user_id: int | None = None, username: str | None = None) -> Job:
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

        # Build env vars from inputs (includes both user-provided and backend-injected values)
        env = dict(os.environ)
        for iname, value in inputs.items():
            env_key = f"INPUT_{iname.upper()}"
            if isinstance(value, list):
                env[env_key] = ",".join(str(v) for v in value)
            else:
                env[env_key] = str(value)

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
        )
        self.jobs[job_id] = job

        asyncio.create_task(self._run_script_job(job, script_path, env))
        return job

    async def _run_script_job(self, job: Job, script_path: str, env: dict):
        job.output.append(f"--- Running {job.script} for {job.service} ---")
        ok = await self._run_command(job, ["bash", script_path], env=env)

        if ok:
            self._sync_service_outputs(job, job.service)

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)

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
        )
        self.jobs[job_id] = job

        asyncio.create_task(self._run_stop_all(job))
        return job

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
            return

        script_path = f"/services/{name}/deploy.sh"
        job.output.append(f"--- Running deploy.sh for {name} ---")
        ok = await self._run_command(job, ["bash", script_path])

        if ok:
            self._sync_service_outputs(job, name)

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)

    async def _run_stop(self, job: Job):
        name = job.service
        service = self.get_service(name)
        if not service:
            job.output.append(f"[ERROR: Service '{name}' not found]")
            job.status = "failed"
            job.finished_at = datetime.now(timezone.utc).isoformat()
            self._persist_job(job)
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

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)

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

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)

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
                except Exception as e:
                    job.output.append(f"[Warning: Could not cache inventory: {e}]")

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)

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

                        session.commit()
                        job.output.append("[Cost data cached successfully]")
                    finally:
                        session.close()
                except Exception as e:
                    job.output.append(f"[Warning: Could not cache cost data: {e}]")

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)

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
            except Exception as e:
                job.output.append(f"[Warning: Could not update cache: {e}]")

        job.status = "completed" if ok else "failed"
        job.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist_job(job)

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
                if object_id is not None:
                    existing.object_id = object_id
                if type_slug is not None:
                    existing.type_slug = type_slug
                if job.schedule_id is not None:
                    existing.schedule_id = job.schedule_id
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
                )
                session.add(record)
            session.commit()
        except Exception as e:
            session.rollback()
            print(f"Failed to persist job {job.id}: {e}")
        finally:
            session.close()
