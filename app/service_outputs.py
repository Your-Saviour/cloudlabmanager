"""Reads and syncs service output files (service_outputs.yaml) from deployed services."""

import json
import os
import yaml
from ansible_runner import SERVICES_DIR


OUTPUTS_FILENAME = "service_outputs.yaml"


def get_service_outputs(service_name: str) -> list[dict]:
    """Read runtime outputs from a service's outputs/service_outputs.yaml."""
    outputs_path = os.path.join(SERVICES_DIR, service_name, "outputs", OUTPUTS_FILENAME)
    if not os.path.isfile(outputs_path):
        return []
    try:
        with open(outputs_path, "r") as f:
            data = yaml.safe_load(f)
        if data and isinstance(data, dict) and "outputs" in data:
            return data["outputs"]
    except Exception:
        pass
    return []


def get_all_service_outputs() -> dict[str, list[dict]]:
    """Get outputs for all services that have a service_outputs.yaml file."""
    results = {}
    if not os.path.isdir(SERVICES_DIR):
        return results
    for dirname in sorted(os.listdir(SERVICES_DIR)):
        service_path = os.path.join(SERVICES_DIR, dirname)
        if not os.path.isdir(service_path):
            continue
        outputs = get_service_outputs(dirname)
        if outputs:
            results[dirname] = outputs
    return results


def sync_credentials_to_inventory(service_name: str, outputs: list[dict]):
    """Upsert credential-type outputs into the Credential inventory type.

    Each credential output is tagged with svc:{service_name}.
    Existing credentials for this service are updated; new ones are created.
    """
    from database import SessionLocal, InventoryType, InventoryObject, InventoryTag

    session = SessionLocal()
    try:
        # Find the credential inventory type
        cred_type = session.query(InventoryType).filter_by(slug="credential").first()
        if not cred_type:
            return

        # Get or create the service tag
        tag_name = f"svc:{service_name}"
        tag = session.query(InventoryTag).filter_by(name=tag_name).first()
        if not tag:
            tag = InventoryTag(name=tag_name, color="#e8984a")
            session.add(tag)
            session.flush()

        # Get existing credential objects with this service tag
        existing_creds = (
            session.query(InventoryObject)
            .filter_by(type_id=cred_type.id)
            .filter(InventoryObject.tags.any(InventoryTag.id == tag.id))
            .all()
        )
        existing_by_name = {}
        for obj in existing_creds:
            obj_data = json.loads(obj.data)
            existing_by_name[obj_data.get("name", "")] = obj

        # Process credential outputs
        credential_outputs = [o for o in outputs if o.get("type") == "credential"]
        for cred in credential_outputs:
            cred_name = f"{service_name} — {cred.get('label', cred['name'])}"
            obj_data = {
                "name": cred_name,
                "credential_type": cred.get("credential_type", "password"),
                "username": cred.get("username", ""),
                "value": cred.get("value", ""),
                "notes": f"Auto-synced from {service_name} deployment",
            }
            search_text = f"{cred_name} {obj_data['username']}".lower()

            existing = existing_by_name.get(cred_name)
            if existing:
                existing.data = json.dumps(obj_data)
                existing.search_text = search_text
            else:
                new_obj = InventoryObject(
                    type_id=cred_type.id,
                    data=json.dumps(obj_data),
                    search_text=search_text,
                )
                session.add(new_obj)
                session.flush()
                new_obj.tags.append(tag)

        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Failed to sync credentials for {service_name}: {e}")
    finally:
        session.close()
