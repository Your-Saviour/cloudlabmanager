"""Loads inventory type definitions from YAML files and syncs them to the database."""

import hashlib
import os
import yaml
from sqlalchemy.orm import Session
from database import InventoryType

INVENTORY_TYPES_DIR = "/inventory_types"

REQUIRED_KEYS = {"slug", "label", "fields"}
VALID_FIELD_TYPES = {"string", "text", "enum", "integer", "boolean", "datetime", "secret", "json"}


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_type_config(config: dict, filename: str) -> list[str]:
    """Validate a type definition. Returns list of error messages."""
    errors = []
    for key in REQUIRED_KEYS:
        if key not in config:
            errors.append(f"{filename}: missing required key '{key}'")

    if "fields" in config:
        for i, field in enumerate(config["fields"]):
            if "name" not in field:
                errors.append(f"{filename}: field {i} missing 'name'")
            if "type" not in field:
                errors.append(f"{filename}: field {i} missing 'type'")
            elif field["type"] not in VALID_FIELD_TYPES:
                errors.append(f"{filename}: field {i} has invalid type '{field['type']}'")

    return errors


def load_type_configs() -> list[dict]:
    """Read all *.yaml files from the inventory_types directory.
    Returns list of parsed configs with added '_raw' and '_hash' keys.
    """
    configs = []
    if not os.path.isdir(INVENTORY_TYPES_DIR):
        print(f"WARN: inventory_types directory not found at {INVENTORY_TYPES_DIR}")
        return configs

    for filename in sorted(os.listdir(INVENTORY_TYPES_DIR)):
        if not filename.endswith((".yaml", ".yml")):
            continue
        filepath = os.path.join(INVENTORY_TYPES_DIR, filename)
        try:
            with open(filepath, "r") as f:
                raw = f.read()
            config = yaml.safe_load(raw)
            if not config or not isinstance(config, dict):
                print(f"WARN: {filename} is empty or not a mapping, skipping")
                continue

            errors = _validate_type_config(config, filename)
            if errors:
                for err in errors:
                    print(f"ERROR: {err}")
                continue

            config["_hash"] = _hash_content(raw)
            config["_filename"] = filename
            configs.append(config)
        except yaml.YAMLError as e:
            print(f"ERROR: Failed to parse {filename}: {e}")
        except Exception as e:
            print(f"ERROR: Failed to read {filename}: {e}")

    return configs


def sync_types_to_db(session: Session, configs: list[dict]) -> list[dict]:
    """Upsert InventoryType rows from loaded configs. Returns the configs list."""
    for config in configs:
        slug = config["slug"]
        content_hash = config["_hash"]

        existing = session.query(InventoryType).filter_by(slug=slug).first()
        if existing:
            if existing.config_hash != content_hash:
                existing.label = config["label"]
                existing.description = config.get("description", "")
                existing.icon = config.get("icon", "")
                existing.config_hash = content_hash
                print(f"  Updated inventory type: {slug}")
        else:
            inv_type = InventoryType(
                slug=slug,
                label=config["label"],
                description=config.get("description", ""),
                icon=config.get("icon", ""),
                config_hash=content_hash,
            )
            session.add(inv_type)
            print(f"  Created inventory type: {slug}")

    session.flush()
    return configs
