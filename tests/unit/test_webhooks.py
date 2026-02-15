"""Unit tests for webhook models and helper functions."""
import json
import pytest
from database import WebhookEndpoint
from models import WebhookEndpointCreate, WebhookEndpointUpdate
from pydantic import ValidationError


class TestWebhookEndpointCreate:
    def test_valid_system_task(self):
        wh = WebhookEndpointCreate(
            name="Test WH",
            job_type="system_task",
            system_task="refresh_instances",
        )
        assert wh.name == "Test WH"
        assert wh.job_type == "system_task"

    def test_valid_service_script(self):
        wh = WebhookEndpointCreate(
            name="Script WH",
            job_type="service_script",
            service_name="n8n-server",
            script_name="deploy.sh",
        )
        assert wh.job_type == "service_script"
        assert wh.service_name == "n8n-server"

    def test_valid_inventory_action(self):
        wh = WebhookEndpointCreate(
            name="Inv WH",
            job_type="inventory_action",
            type_slug="servers",
            action_name="deploy",
        )
        assert wh.job_type == "inventory_action"

    def test_name_too_long(self):
        with pytest.raises(ValidationError):
            WebhookEndpointCreate(
                name="x" * 101,
                job_type="system_task",
                system_task="refresh_instances",
            )

    def test_name_empty(self):
        with pytest.raises(ValidationError):
            WebhookEndpointCreate(
                name="   ",
                job_type="system_task",
                system_task="refresh_instances",
            )

    def test_invalid_job_type(self):
        with pytest.raises(ValidationError):
            WebhookEndpointCreate(
                name="Bad",
                job_type="invalid",
            )

    def test_name_stripped(self):
        wh = WebhookEndpointCreate(
            name="  padded name  ",
            job_type="system_task",
            system_task="refresh_instances",
        )
        assert wh.name == "padded name"

    def test_defaults(self):
        wh = WebhookEndpointCreate(
            name="Defaults",
            job_type="system_task",
            system_task="refresh_instances",
        )
        assert wh.is_enabled is True
        assert wh.description is None
        assert wh.payload_mapping is None
        assert wh.object_id is None

    def test_with_payload_mapping(self):
        wh = WebhookEndpointCreate(
            name="Mapped",
            job_type="service_script",
            service_name="svc",
            script_name="run.sh",
            payload_mapping={"BRANCH": "$.ref"},
        )
        assert wh.payload_mapping == {"BRANCH": "$.ref"}


class TestWebhookEndpointUpdate:
    def test_all_none(self):
        update = WebhookEndpointUpdate()
        assert update.name is None
        assert update.description is None
        assert update.payload_mapping is None
        assert update.is_enabled is None

    def test_partial_update(self):
        update = WebhookEndpointUpdate(name="New Name", is_enabled=False)
        assert update.name == "New Name"
        assert update.is_enabled is False
        assert update.description is None

    def test_payload_mapping_update(self):
        update = WebhookEndpointUpdate(
            payload_mapping={"KEY": "$.value"}
        )
        assert update.payload_mapping == {"KEY": "$.value"}


class TestWebhookEndpointModel:
    def test_create_orm_object(self, db_session):
        webhook = WebhookEndpoint(
            name="ORM Test",
            token="abc123def456",
            job_type="system_task",
            system_task="refresh_instances",
            is_enabled=True,
        )
        db_session.add(webhook)
        db_session.commit()
        db_session.refresh(webhook)

        assert webhook.id is not None
        assert webhook.name == "ORM Test"
        assert webhook.trigger_count == 0
        assert webhook.created_at is not None

    def test_payload_mapping_json_roundtrip(self, db_session):
        mapping = {"BRANCH": "$.ref", "REPO": "$.repository.name"}
        webhook = WebhookEndpoint(
            name="JSON Test",
            token="json123abc456",
            job_type="system_task",
            system_task="refresh_instances",
            is_enabled=True,
            payload_mapping=json.dumps(mapping),
        )
        db_session.add(webhook)
        db_session.commit()
        db_session.refresh(webhook)

        loaded = json.loads(webhook.payload_mapping)
        assert loaded == mapping

    def test_token_unique_constraint(self, db_session):
        from sqlalchemy.exc import IntegrityError

        wh1 = WebhookEndpoint(
            name="WH1", token="sametoken12345678",
            job_type="system_task", system_task="refresh_instances",
        )
        wh2 = WebhookEndpoint(
            name="WH2", token="sametoken12345678",
            job_type="system_task", system_task="refresh_instances",
        )
        db_session.add(wh1)
        db_session.flush()

        db_session.add(wh2)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()


class TestExtractInputsFromPayload:
    def test_basic_extraction(self):
        from routes.webhook_routes import _extract_inputs_from_payload

        payload = {"ref": "refs/heads/main", "repository": {"name": "myrepo"}}
        mapping = {"BRANCH": "$.ref", "REPO": "$.repository.name"}

        result = _extract_inputs_from_payload(payload, mapping)
        assert result == {"BRANCH": "refs/heads/main", "REPO": "myrepo"}

    def test_empty_payload(self):
        from routes.webhook_routes import _extract_inputs_from_payload

        result = _extract_inputs_from_payload({}, {"BRANCH": "$.ref"})
        assert result == {}

    def test_empty_mapping(self):
        from routes.webhook_routes import _extract_inputs_from_payload

        result = _extract_inputs_from_payload({"ref": "main"}, {})
        assert result == {}

    def test_none_inputs(self):
        from routes.webhook_routes import _extract_inputs_from_payload

        assert _extract_inputs_from_payload(None, {"K": "$.v"}) == {}
        assert _extract_inputs_from_payload({"k": "v"}, None) == {}

    def test_missing_jsonpath_match(self):
        from routes.webhook_routes import _extract_inputs_from_payload

        payload = {"foo": "bar"}
        mapping = {"MISSING": "$.nonexistent.path"}

        result = _extract_inputs_from_payload(payload, mapping)
        assert result == {}

    def test_invalid_jsonpath_expression(self):
        from routes.webhook_routes import _extract_inputs_from_payload

        payload = {"foo": "bar"}
        mapping = {"BAD": "[[[invalid"}

        # Should not raise, just skip the bad expression
        result = _extract_inputs_from_payload(payload, mapping)
        assert "BAD" not in result


class TestWebhookPermissions:
    def test_webhook_permissions_seeded(self, seeded_db):
        from database import Permission

        session = seeded_db
        webhook_perms = (
            session.query(Permission)
            .filter(Permission.codename.like("webhooks.%"))
            .all()
        )
        codenames = {p.codename for p in webhook_perms}
        assert codenames == {
            "webhooks.view",
            "webhooks.create",
            "webhooks.edit",
            "webhooks.delete",
        }
