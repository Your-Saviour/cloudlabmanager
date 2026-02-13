"""Blueprint deployment orchestrator.

Deploys multiple services sequentially as defined in a blueprint,
tracking per-service progress in the BlueprintDeployment record.
"""

import asyncio
import json
from datetime import datetime, timezone
from database import SessionLocal, BlueprintDeployment


class BlueprintOrchestrator:
    def __init__(self, ansible_runner):
        self.runner = ansible_runner

    async def deploy_blueprint(self, deployment_id: int) -> None:
        """Execute a blueprint deployment by running each service in order."""
        session = SessionLocal()
        try:
            dep = session.query(BlueprintDeployment).filter_by(id=deployment_id).first()
            if not dep:
                return

            dep.status = "running"
            dep.started_at = datetime.now(timezone.utc)
            session.commit()

            services = json.loads(dep.blueprint.services) if dep.blueprint.services else []
            progress = json.loads(dep.progress) if dep.progress else {}

            all_ok = True
            job_ids = []

            for i, svc_config in enumerate(services):
                service_name = svc_config.get("name", f"service_{i}")

                # Update progress to running
                progress[service_name] = "running"
                dep.progress = json.dumps(progress)
                session.commit()

                try:
                    # Check the service actually exists
                    svc = self.runner.get_service(service_name)
                    if not svc:
                        progress[service_name] = "failed"
                        dep.progress = json.dumps(progress)
                        session.commit()
                        all_ok = False
                        break

                    # Deploy the service
                    job = await self.runner.deploy_service(
                        service_name,
                        user_id=dep.deployed_by,
                        username=None,
                    )
                    job_ids.append(job.id)

                    # Wait for the job to complete
                    while job.status == "running":
                        await asyncio.sleep(1)

                    if job.status == "completed":
                        progress[service_name] = "completed"
                    else:
                        progress[service_name] = "failed"
                        all_ok = False
                        dep.progress = json.dumps(progress)
                        session.commit()
                        break

                except Exception:
                    progress[service_name] = "failed"
                    all_ok = False
                    dep.progress = json.dumps(progress)
                    session.commit()
                    break

                dep.progress = json.dumps(progress)
                session.commit()

            dep.status = "completed" if all_ok else "partial"
            dep.finished_at = datetime.now(timezone.utc)
            session.commit()

        except Exception:
            try:
                dep = session.query(BlueprintDeployment).filter_by(id=deployment_id).first()
                if dep:
                    dep.status = "failed"
                    dep.finished_at = datetime.now(timezone.utc)
                    session.commit()
            except Exception:
                pass
        finally:
            session.close()
