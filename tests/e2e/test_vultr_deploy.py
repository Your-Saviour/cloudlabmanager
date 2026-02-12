"""End-to-end tests against the real running CloudLabManager.

These tests hit the ACTUAL cloudlabmanager service over HTTP.
They deploy and destroy real Vultr VMs.

Prerequisites:
  docker compose up -d cloudlabmanager   # start the real app
  # Complete initial setup via the UI or API first

Run with:
  docker compose --profile test run --rm test tests/e2e/ -v -s --timeout=600
"""
import os
import pytest
import asyncio
import httpx
import subprocess
import json

pytestmark = pytest.mark.e2e

BASE_URL = os.environ.get("E2E_BASE_URL", "http://cloudlabmanager:8000")
WS_URL = BASE_URL.replace("http://", "ws://")
TEST_USERNAME = "e2e_test_admin"
TEST_PASSWORD = "e2eTestPass9876!"

SERVICE_NAME = "test-ubuntu"
INSTANCE_LABEL = "testUbuntu"
INSTANCE_REGION = "mel"


@pytest.fixture(scope="function")
async def e2e_session():
    """Create a test superadmin on the real app's DB, then return an authenticated client."""

    create_user_script = f"""
import sys
sys.path.insert(0, '/app/app')
from database import SessionLocal, User, Role, Base
from auth import hash_password
from datetime import datetime, timezone

session = SessionLocal()
existing = session.query(User).filter_by(username='{TEST_USERNAME}').first()
if not existing:
    super_admin = session.query(Role).filter_by(name='super-admin').first()
    user = User(
        username='{TEST_USERNAME}',
        password_hash=hash_password('{TEST_PASSWORD}'),
        is_active=True,
        email='e2e@test.local',
        invite_accepted_at=datetime.now(timezone.utc),
    )
    if super_admin:
        user.roles.append(super_admin)
    session.add(user)
    session.commit()
    print('Created e2e test user')
else:
    print('E2E test user already exists')
session.close()
"""
    result = subprocess.run(
        ["docker", "exec", "cloud-lab-manager", "python3", "-c", create_user_script],
        capture_output=True, text=True, timeout=15,
    )
    print(f"Create user: {result.stdout.strip()} {result.stderr.strip()}")
    assert result.returncode == 0, f"Failed to create test user: {result.stderr}"

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as c:
        status_resp = await c.get("/api/auth/status")
        assert status_resp.status_code == 200, f"App not reachable at {BASE_URL}"
        assert status_resp.json()["setup_complete"] is True, \
            "App setup not complete. Run setup first."

        resp = await c.post("/api/auth/login", json={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD,
        })
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        token = resp.json()["access_token"]

        c.headers["Authorization"] = f"Bearer {token}"
        c._e2e_token = token
        yield c

    cleanup_script = f"""
import sys
sys.path.insert(0, '/app/app')
from database import SessionLocal, User

session = SessionLocal()
user = session.query(User).filter_by(username='{TEST_USERNAME}').first()
if user:
    session.delete(user)
    session.commit()
    print('Deleted e2e test user')
session.close()
"""
    subprocess.run(
        ["docker", "exec", "cloud-lab-manager", "python3", "-c", cleanup_script],
        capture_output=True, text=True, timeout=15,
    )


async def poll_job(client, job_id, max_polls=120, interval=5, label="job"):
    """Poll a job until it completes or fails. Returns (status, output)."""
    status = "running"
    for i in range(max_polls):
        resp = await client.get(f"/api/jobs/{job_id}")
        data = resp.json()
        status = data["status"]
        if status in ("completed", "failed"):
            break
        if i % 12 == 0:
            output_lines = len(data.get("output", []))
            print(f"  ... polling {label} ({i * interval}s, {output_lines} lines)")
        await asyncio.sleep(interval)

    resp = await client.get(f"/api/jobs/{job_id}")
    output = resp.json().get("output", [])
    return status, output


async def destroy_instance(client, label, region):
    """Destroy an instance and wait for completion. Best-effort, won't raise."""
    try:
        print(f"\n>>> Destroying instance: label={label}, region={region}")
        resp = await client.post("/api/instances/stop", json={
            "label": label,
            "region": region,
        })
        if resp.status_code != 200:
            print(f"  Destroy request failed: {resp.status_code} {resp.text}")
            return
        destroy_job_id = resp.json()["job_id"]
        print(f">>> Destroy started: job_id={destroy_job_id}")

        status, output = await poll_job(client, destroy_job_id, max_polls=60, label="destroy")
        print(f">>> Destroy finished: status={status} ({len(output)} lines)")
        for line in output[-10:]:
            print(f"  | {line}")
    except Exception as e:
        print(f"  Destroy failed with exception: {e}")


class TestVultrDeploy:
    """Full deployment lifecycle: deploy -> SSH -> destroy instance."""

    @pytest.mark.timeout(600)
    async def test_deploy_ssh_and_destroy(self, e2e_session):
        c = e2e_session
        deployed = False
        errors = []

        try:
            # ── 1. Verify test-ubuntu service exists ──
            resp = await c.get("/api/services")
            assert resp.status_code == 200
            names = [s["name"] for s in resp.json()["services"]]
            assert SERVICE_NAME in names, f"{SERVICE_NAME} not in services: {names}"
            print(f"\n✓ Service '{SERVICE_NAME}' found")

            # ── 2. Deploy test-ubuntu ──
            resp = await c.post(f"/api/services/{SERVICE_NAME}/deploy")
            assert resp.status_code == 200, f"Deploy failed: {resp.text}"
            deploy_job_id = resp.json()["job_id"]
            assert resp.json()["status"] == "running"
            deployed = True
            print(f">>> Deploy started: job_id={deploy_job_id}")

            # ── 3. Poll deploy job until completion ──
            status, output = await poll_job(c, deploy_job_id, label="deploy")
            print(f">>> Deploy finished: status={status} ({len(output)} lines)")
            for line in output[-20:]:
                print(f"  | {line}")
            assert status == "completed", f"Deploy job {deploy_job_id} ended with: {status}"

            # ── 4. Refresh instances and verify VM appears ──
            resp = await c.post("/api/instances/refresh")
            assert resp.status_code == 200, f"Refresh failed: {resp.text}"
            refresh_job_id = resp.json()["job_id"]
            print(f"\n>>> Refreshing instances: job_id={refresh_job_id}")

            refresh_status, _ = await poll_job(c, refresh_job_id, max_polls=30, label="refresh")
            assert refresh_status == "completed", f"Refresh failed: {refresh_status}"

            resp = await c.get("/api/instances")
            assert resp.status_code == 200
            instances_data = resp.json().get("instances", {})
            hosts = instances_data.get("all", {}).get("hosts", {})
            instance_labels = list(hosts.keys())
            instance_ip = None
            if INSTANCE_LABEL in hosts:
                instance_ip = hosts[INSTANCE_LABEL].get("ansible_host")
            print(f"✓ Instances after deploy: {instance_labels}")
            assert INSTANCE_LABEL in instance_labels, \
                f"{INSTANCE_LABEL} not found in instances: {instance_labels}"
            print(f"✓ Instance '{INSTANCE_LABEL}' found, IP: {instance_ip}")

            # ── 5. Test SSH via WebSocket ──
            import websockets
            token = c._e2e_token
            ws_uri = f"{WS_URL}/api/instances/ssh/{INSTANCE_LABEL}?token={token}"
            print(f"\n>>> Testing SSH WebSocket to {INSTANCE_LABEL}...")

            async with websockets.connect(ws_uri, close_timeout=10) as ws:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                msg = json.loads(raw)
                assert msg["type"] == "connected", f"Expected 'connected', got: {msg}"
                print(f"✓ SSH connected: user={msg.get('user')}, ip={msg.get('ip')}")

                await asyncio.sleep(1)

                await ws.send(json.dumps({"type": "input", "data": "echo E2E_SSH_TEST_OK\n"}))

                ssh_output = ""
                for _ in range(20):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        msg = json.loads(raw)
                        if msg.get("type") == "output":
                            ssh_output += msg.get("data", "")
                            if "E2E_SSH_TEST_OK" in ssh_output:
                                break
                    except asyncio.TimeoutError:
                        break

                print(f"✓ SSH output received ({len(ssh_output)} chars)")
                assert "E2E_SSH_TEST_OK" in ssh_output, \
                    f"SSH echo test failed. Output: {ssh_output[:200]}"
                print("✓ SSH echo test passed")

        except Exception as e:
            errors.append(e)
            print(f"\n!!! Test error: {e}")

        finally:
            # ── ALWAYS destroy the instance if we deployed ──
            if deployed:
                await destroy_instance(c, INSTANCE_LABEL, INSTANCE_REGION)

                # Refresh and verify instance is gone
                try:
                    resp = await c.post("/api/instances/refresh")
                    if resp.status_code == 200:
                        verify_job_id = resp.json()["job_id"]
                        verify_status, _ = await poll_job(c, verify_job_id, max_polls=30,
                                                          label="verify-refresh")
                        resp = await c.get("/api/instances")
                        instances_data = resp.json().get("instances", {})
                        remaining_hosts = instances_data.get("all", {}).get("hosts", {})
                        remaining = list(remaining_hosts.keys())
                        print(f"✓ Instances after destroy: {remaining}")
                        assert INSTANCE_LABEL not in remaining, \
                            f"{INSTANCE_LABEL} still present after destroy: {remaining}"
                        print("✓ Instance successfully destroyed")
                except Exception as e:
                    print(f"  Verify cleanup error: {e}")

        # Re-raise the original error if any
        if errors:
            raise errors[0]
