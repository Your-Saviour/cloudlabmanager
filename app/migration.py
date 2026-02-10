"""One-time migration from database.json to SQLite."""

import json
import os
from datetime import datetime, timezone
from database import (
    SessionLocal, User, Role, AppMetadata, JobRecord,
    create_tables, utcnow,
)
from permissions import seed_permissions

JSON_DB_PATH = "/data/database.json"
SQLITE_DB_PATH = "/data/cloudlab.db"


def needs_migration() -> bool:
    """Check if migration is needed: SQLite doesn't exist but JSON does with data."""
    if os.path.isfile(SQLITE_DB_PATH):
        return False
    if not os.path.isfile(JSON_DB_PATH):
        return False
    try:
        with open(JSON_DB_PATH, "r") as f:
            data = json.load(f)
        return bool(data)
    except (json.JSONDecodeError, IOError):
        return False


def run_migration():
    """Migrate data from database.json to SQLite."""
    print("Starting JSON -> SQLite migration...")

    with open(JSON_DB_PATH, "r") as f:
        data = json.load(f)

    # Create tables and seed
    create_tables()

    session = SessionLocal()
    try:
        # Load inventory type configs for dynamic permission generation
        from type_loader import load_type_configs
        type_configs = load_type_configs()
        seed_permissions(session, type_configs)
        session.commit()

        # Get super-admin role
        super_admin = session.query(Role).filter_by(name="super-admin").first()

        # Migrate users
        json_users = data.get("users", {})
        for username, user_data in json_users.items():
            user = User(
                username=username,
                password_hash=user_data.get("password_hash"),
                is_active=True,
                created_at=utcnow(),
                invite_accepted_at=utcnow(),
            )
            if super_admin:
                user.roles.append(super_admin)
            session.add(user)
        session.flush()
        print(f"  Migrated {len(json_users)} user(s)")

        # Migrate app metadata
        metadata_keys = ["secret_key", "vault_password", "instances_cache",
                         "instances_cache_time", "HOST_HOSTNAME", "dns_id"]
        for key in metadata_keys:
            if key in data:
                AppMetadata.set(session, key, data[key])
                print(f"  Migrated metadata: {key}")

        # Migrate jobs
        json_jobs = data.get("jobs", {})
        for job_id, job_data in json_jobs.items():
            job = JobRecord(
                id=job_id,
                service=job_data.get("service", ""),
                action=job_data.get("action", ""),
                script=job_data.get("script"),
                status=job_data.get("status", "unknown"),
                started_at=job_data.get("started_at"),
                finished_at=job_data.get("finished_at"),
                output=json.dumps(job_data.get("output", [])),
                deployment_id=job_data.get("deployment_id"),
            )
            session.add(job)
        print(f"  Migrated {len(json_jobs)} job(s)")

        session.commit()
        print("Migration complete.")

        # Rename old file
        migrated_path = JSON_DB_PATH + ".migrated"
        os.rename(JSON_DB_PATH, migrated_path)
        print(f"  Renamed {JSON_DB_PATH} -> {migrated_path}")

    except Exception as e:
        session.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        session.close()
