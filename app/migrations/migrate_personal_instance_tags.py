"""
One-time migration: retag personal-jump-host instances to generic personal-instance tags.

Updates:
  - Vultr instance tags (via Vultr API)
  - Local inventory_objects data (SQLite)

Tag mapping:
  personal-jump-host   -> personal-instance
  pjh-user:{username}  -> pi-user:{username}
  pjh-ttl:{hours}      -> pi-ttl:{hours}
  (new)                 -> pi-service:jump-hosts

Run from inside the cloudlabmanager container:
  python3 /app/migrations/migrate_personal_instance_tags.py
"""

import json
import os
import subprocess
import sys

import httpx
import logging
import yaml

sys.path.insert(0, "/app")
from database import SessionLocal, InventoryType, InventoryObject

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrate_tags")

OLD_TAG = "personal-jump-host"
NEW_TAG = "personal-instance"
SERVICE_TAG = "pi-service:jump-hosts"

TAG_MAP = {
    "personal-jump-host": "personal-instance",
}
PREFIX_MAP = {
    "pjh-user:": "pi-user:",
    "pjh-ttl:": "pi-ttl:",
}

VAULT_PASS_FILE = "/tmp/.vault_pass.txt"
VAULT_SECRETS_FILE = "/vault/secrets.yml"


def migrate_tag(tag: str) -> str:
    """Convert a single old-style tag to new-style."""
    if tag in TAG_MAP:
        return TAG_MAP[tag]
    for old_prefix, new_prefix in PREFIX_MAP.items():
        if tag.startswith(old_prefix):
            return new_prefix + tag[len(old_prefix):]
    return tag


def migrate_tags(tags: list[str]) -> list[str]:
    """Convert a list of old tags to new tags, adding pi-service if missing."""
    new_tags = [migrate_tag(t) for t in tags]
    if SERVICE_TAG not in new_tags:
        new_tags.append(SERVICE_TAG)
    return new_tags


def update_vultr_tags(vultr_id: str, new_tags: list[str], api_key: str) -> bool:
    """Update tags on a Vultr instance via the API."""
    url = f"https://api.vultr.com/v2/instances/{vultr_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = httpx.patch(url, json={"tags": new_tags}, headers=headers, timeout=30)
        if resp.status_code in (200, 202, 204):
            return True
        logger.error("Vultr API error for %s: %s %s", vultr_id, resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.error("Vultr API request failed for %s: %s", vultr_id, e)
        return False


def get_vultr_api_key() -> str | None:
    """Get Vultr API key by decrypting the vault or from environment."""
    # Try environment variable first
    api_key = os.environ.get("VULTR_API_KEY")
    if api_key:
        return api_key

    # Try decrypting the vault using ansible-vault
    if os.path.isfile(VAULT_PASS_FILE) and os.path.isfile(VAULT_SECRETS_FILE):
        try:
            result = subprocess.run(
                ["ansible-vault", "view", VAULT_SECRETS_FILE, "--vault-password-file", VAULT_PASS_FILE],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                secrets = yaml.safe_load(result.stdout)
                if secrets and isinstance(secrets, dict):
                    api_key = secrets.get("vultr_api_key")
                    if api_key:
                        return api_key
        except Exception as e:
            logger.warning("Failed to decrypt vault: %s", e)

    return None


def main():
    api_key = get_vultr_api_key()

    if not api_key:
        logger.error("Cannot find Vultr API key. Set VULTR_API_KEY env var or ensure vault is available.")
        sys.exit(1)

    session = SessionLocal()
    try:
        inv_type = session.query(InventoryType).filter_by(slug="server").first()
        if not inv_type:
            logger.info("No 'server' inventory type found. Nothing to migrate.")
            return

        migrated_db = 0
        migrated_vultr = 0
        skipped = 0

        for obj in session.query(InventoryObject).filter_by(type_id=inv_type.id).all():
            data = json.loads(obj.data)
            vultr_tags = data.get("vultr_tags", [])

            if OLD_TAG not in vultr_tags:
                continue

            hostname = data.get("hostname", "unknown")
            vultr_id = data.get("vultr_id", "")
            new_tags = migrate_tags(vultr_tags)

            logger.info("Migrating %s (vultr_id=%s)", hostname, vultr_id)
            logger.info("  Old tags: %s", vultr_tags)
            logger.info("  New tags: %s", new_tags)

            # Update local DB
            data["vultr_tags"] = new_tags
            obj.data = json.dumps(data)
            migrated_db += 1

            # Update Vultr
            if vultr_id:
                if update_vultr_tags(vultr_id, new_tags, api_key):
                    migrated_vultr += 1
                    logger.info("  Vultr tags updated successfully")
                else:
                    logger.warning("  Vultr tag update FAILED (DB still updated)")
            else:
                logger.warning("  No vultr_id — skipping Vultr API update")
                skipped += 1

        session.commit()
        logger.info("")
        logger.info("Migration complete: %d DB records updated, %d Vultr instances retagged, %d skipped",
                     migrated_db, migrated_vultr, skipped)

    finally:
        session.close()


if __name__ == "__main__":
    main()
