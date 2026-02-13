import json
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc
from db_session import get_db_session
from auth import get_current_user
from permissions import require_permission
from audit import log_action
from database import Incident, IncidentTimeline, IncidentArtifact, User, incident_responders, utcnow
from models import IncidentCreate, IncidentUpdate, TimelineEntryCreate, ArtifactCreate

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

ARTIFACTS_DIR = "/data/persistent/incidents"


def _serialize_incident(inc: Incident) -> dict:
    return {
        "id": inc.id,
        "title": inc.title,
        "description": inc.description,
        "severity": inc.severity,
        "status": inc.status,
        "commander_id": inc.commander_id,
        "created_by": inc.created_by,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
        "updated_at": inc.updated_at.isoformat() if inc.updated_at else None,
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
    }


def _serialize_responder(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    }


def _serialize_timeline(entry: IncidentTimeline) -> dict:
    return {
        "id": entry.id,
        "incident_id": entry.incident_id,
        "entry_type": entry.entry_type,
        "content": entry.content,
        "metadata": json.loads(entry.metadata) if entry.metadata else None,
        "user_id": entry.user_id,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _serialize_artifact(art: IncidentArtifact) -> dict:
    return {
        "id": art.id,
        "incident_id": art.incident_id,
        "name": art.name,
        "artifact_type": art.artifact_type,
        "file_path": art.file_path,
        "size_bytes": art.size_bytes,
        "uploaded_by": art.uploaded_by,
        "created_at": art.created_at.isoformat() if art.created_at else None,
    }


# --- Incident CRUD ---


@router.get("")
async def list_incidents(
        status: str | None = None,
        severity: str | None = None,
        user: User = Depends(require_permission("incidents.view")),
        session: Session = Depends(get_db_session)):
    query = session.query(Incident).order_by(desc(Incident.created_at))
    if status:
        query = query.filter(Incident.status == status)
    if severity:
        query = query.filter(Incident.severity == severity)
    incidents = query.all()
    return {"incidents": [_serialize_incident(i) for i in incidents]}


@router.get("/{incident_id}")
async def get_incident(
        incident_id: int,
        user: User = Depends(require_permission("incidents.view")),
        session: Session = Depends(get_db_session)):
    incident = session.query(Incident).filter_by(id=incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    result = _serialize_incident(incident)
    result["responders"] = [_serialize_responder(r) for r in incident.responders]
    result["timeline"] = [_serialize_timeline(e) for e in incident.timeline_entries]
    return result


@router.post("")
async def create_incident(
        body: IncidentCreate,
        request: Request,
        user: User = Depends(require_permission("incidents.manage")),
        session: Session = Depends(get_db_session)):
    incident = Incident(
        title=body.title,
        description=body.description,
        severity=body.severity,
        status="open",
        commander_id=user.id,
        created_by=user.id,
    )
    session.add(incident)
    session.flush()

    # Add responders if provided
    if body.responder_ids:
        responders = session.query(User).filter(User.id.in_(body.responder_ids)).all()
        incident.responders = responders

    # Create initial timeline entry
    initial_entry = IncidentTimeline(
        incident_id=incident.id,
        entry_type="status_change",
        content="Incident created",
        user_id=user.id,
    )
    session.add(initial_entry)
    session.flush()

    log_action(session, user.id, user.username, "incident.create",
               f"incidents/{incident.id}",
               details={"title": body.title, "severity": body.severity},
               ip_address=request.client.host if request.client else None)

    result = _serialize_incident(incident)
    result["responders"] = [_serialize_responder(r) for r in incident.responders]
    result["timeline"] = [_serialize_timeline(initial_entry)]
    return result


@router.put("/{incident_id}")
async def update_incident(
        incident_id: int,
        body: IncidentUpdate,
        request: Request,
        user: User = Depends(require_permission("incidents.manage")),
        session: Session = Depends(get_db_session)):
    incident = session.query(Incident).filter_by(id=incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    old_status = incident.status

    if body.title is not None:
        incident.title = body.title
    if body.description is not None:
        incident.description = body.description
    if body.severity is not None:
        incident.severity = body.severity
    if body.status is not None:
        incident.status = body.status
    if body.commander_id is not None:
        incident.commander_id = body.commander_id

    # If status changed, add a timeline entry
    if body.status is not None and body.status != old_status:
        timeline_entry = IncidentTimeline(
            incident_id=incident.id,
            entry_type="status_change",
            content=f"Status changed from {old_status} to {body.status}",
            user_id=user.id,
        )
        session.add(timeline_entry)

        # If resolved, set resolved_at
        if body.status == "resolved":
            incident.resolved_at = utcnow()

    session.flush()

    log_action(session, user.id, user.username, "incident.update",
               f"incidents/{incident_id}",
               details=body.model_dump(exclude_none=True),
               ip_address=request.client.host if request.client else None)

    return _serialize_incident(incident)


# --- Timeline ---


@router.post("/{incident_id}/timeline")
async def add_timeline_entry(
        incident_id: int,
        body: TimelineEntryCreate,
        request: Request,
        user: User = Depends(require_permission("incidents.respond")),
        session: Session = Depends(get_db_session)):
    incident = session.query(Incident).filter_by(id=incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    entry = IncidentTimeline(
        incident_id=incident_id,
        entry_type=body.entry_type,
        content=body.content,
        user_id=user.id,
    )
    session.add(entry)
    session.flush()

    log_action(session, user.id, user.username, "incident.timeline.add",
               f"incidents/{incident_id}/timeline/{entry.id}",
               details={"entry_type": body.entry_type},
               ip_address=request.client.host if request.client else None)

    return _serialize_timeline(entry)


@router.get("/{incident_id}/timeline")
async def get_timeline(
        incident_id: int,
        user: User = Depends(require_permission("incidents.view")),
        session: Session = Depends(get_db_session)):
    incident = session.query(Incident).filter_by(id=incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    entries = (
        session.query(IncidentTimeline)
        .filter_by(incident_id=incident_id)
        .order_by(IncidentTimeline.created_at)
        .all()
    )
    return {"timeline": [_serialize_timeline(e) for e in entries]}


# --- Artifacts ---


@router.post("/{incident_id}/artifacts")
async def create_artifact(
        incident_id: int,
        body: ArtifactCreate,
        request: Request,
        user: User = Depends(require_permission("incidents.respond")),
        session: Session = Depends(get_db_session)):
    incident = session.query(Incident).filter_by(id=incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    file_path = None
    size_bytes = None

    if body.content:
        artifact_dir = os.path.join(ARTIFACTS_DIR, str(incident_id))
        os.makedirs(artifact_dir, exist_ok=True)
        file_path = os.path.join(artifact_dir, body.name)
        with open(file_path, "w") as f:
            f.write(body.content)
        size_bytes = len(body.content.encode("utf-8"))

    artifact = IncidentArtifact(
        incident_id=incident_id,
        name=body.name,
        artifact_type=body.artifact_type,
        file_path=file_path,
        size_bytes=size_bytes,
        uploaded_by=user.id,
    )
    session.add(artifact)
    session.flush()

    log_action(session, user.id, user.username, "incident.artifact.create",
               f"incidents/{incident_id}/artifacts/{artifact.id}",
               details={"name": body.name, "artifact_type": body.artifact_type},
               ip_address=request.client.host if request.client else None)

    return _serialize_artifact(artifact)


@router.get("/{incident_id}/artifacts")
async def list_artifacts(
        incident_id: int,
        user: User = Depends(require_permission("incidents.view")),
        session: Session = Depends(get_db_session)):
    incident = session.query(Incident).filter_by(id=incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    artifacts = (
        session.query(IncidentArtifact)
        .filter_by(incident_id=incident_id)
        .order_by(IncidentArtifact.created_at)
        .all()
    )
    return {"artifacts": [_serialize_artifact(a) for a in artifacts]}


@router.delete("/{incident_id}/artifacts/{artifact_id}")
async def delete_artifact(
        incident_id: int,
        artifact_id: int,
        request: Request,
        user: User = Depends(require_permission("incidents.manage")),
        session: Session = Depends(get_db_session)):
    artifact = session.query(IncidentArtifact).filter_by(
        id=artifact_id, incident_id=incident_id
    ).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    log_action(session, user.id, user.username, "incident.artifact.delete",
               f"incidents/{incident_id}/artifacts/{artifact_id}",
               details={"name": artifact.name},
               ip_address=request.client.host if request.client else None)

    session.delete(artifact)
    session.flush()
    return {"status": "deleted"}


# --- Responders ---


@router.put("/{incident_id}/responders")
async def update_responders(
        incident_id: int,
        body: dict,
        request: Request,
        user: User = Depends(require_permission("incidents.manage")),
        session: Session = Depends(get_db_session)):
    incident = session.query(Incident).filter_by(id=incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    responder_ids = body.get("responder_ids", [])
    responders = session.query(User).filter(User.id.in_(responder_ids)).all()
    incident.responders = responders
    session.flush()

    log_action(session, user.id, user.username, "incident.responders.update",
               f"incidents/{incident_id}/responders",
               details={"responder_ids": responder_ids},
               ip_address=request.client.host if request.client else None)

    return {"responders": [_serialize_responder(r) for r in incident.responders]}
