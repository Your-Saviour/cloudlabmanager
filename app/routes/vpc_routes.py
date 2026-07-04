import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from database import User, AppMetadata
from permissions import require_permission
from db_session import get_db_session
from audit import log_action

router = APIRouter(prefix="/api/vpc", tags=["vpc"])

# Alphanumeric, hyphens, underscores, dots, spaces — safe for Ansible extra vars
_SAFE_RE = re.compile(r"^[a-zA-Z0-9._\- ]+$")
# Vultr IDs are UUIDs (hex + hyphens)
_VULTR_ID_RE = re.compile(r"^[a-f0-9\-]+$")
# CIDR subnet base (IPv4 dotted quad)
_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

EMPTY_REPORT = {"vpcs": [], "instances": {}, "firewall_groups": []}


def _validate_safe_string(v: str, field_name: str, max_len: int = 200) -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{field_name} is required")
    if len(v) > max_len:
        raise ValueError(f"{field_name} must be {max_len} characters or fewer")
    if not _SAFE_RE.match(v):
        raise ValueError(f"{field_name} contains invalid characters")
    return v


def _validate_vultr_id(v: str, field_name: str) -> str:
    v = v.strip()
    if not v or not _VULTR_ID_RE.match(v):
        raise ValueError(f"{field_name} must be a valid Vultr UUID")
    return v


def _check_path_id(value: str, field_name: str) -> str:
    """Validate a Vultr UUID arriving as a path parameter."""
    value = value.strip()
    if not value or not _VULTR_ID_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid Vultr UUID")
    return value


class CreateVpcRequest(BaseModel):
    description: str
    region: str
    v4_subnet: str | None = None
    v4_subnet_mask: int | None = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        return _validate_safe_string(v, "description", max_len=200)

    @field_validator("region")
    @classmethod
    def validate_region(cls, v: str) -> str:
        return _validate_safe_string(v, "region", max_len=20)

    @field_validator("v4_subnet")
    @classmethod
    def validate_subnet(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not _IPV4_RE.match(v):
            raise ValueError("v4_subnet must be a valid IPv4 address")
        return v

    @field_validator("v4_subnet_mask")
    @classmethod
    def validate_subnet_mask(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not 1 <= v <= 32:
            raise ValueError("v4_subnet_mask must be between 1 and 32")
        return v


class VpcIdRequest(BaseModel):
    vpc_id: str

    @field_validator("vpc_id")
    @classmethod
    def validate_vpc_id(cls, v: str) -> str:
        return _validate_vultr_id(v, "vpc_id")


class CreateFirewallGroupRequest(BaseModel):
    description: str

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        return _validate_safe_string(v, "description", max_len=200)


class AddFirewallRuleRequest(BaseModel):
    protocol: str | None = None
    port: str | None = None
    subnet: str | None = None
    subnet_size: int | None = None
    ip_type: str | None = None
    source: str | None = None
    notes: str | None = None

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip().lower()
        if v not in ("tcp", "udp", "icmp", "gre", "esp", "ah"):
            raise ValueError("protocol must be one of tcp, udp, icmp, gre, esp, ah")
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        # Single port or Vultr-style range "start:end"
        if not re.match(r"^\d{1,5}(:\d{1,5})?$", v):
            raise ValueError("port must be a port number or range (e.g. 443 or 8000:8100)")
        return v

    @field_validator("subnet")
    @classmethod
    def validate_subnet(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not _IPV4_RE.match(v):
            raise ValueError("subnet must be a valid IPv4 address")
        return v

    @field_validator("subnet_size")
    @classmethod
    def validate_subnet_size(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not 0 <= v <= 32:
            raise ValueError("subnet_size must be between 0 and 32")
        return v

    @field_validator("ip_type")
    @classmethod
    def validate_ip_type(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip().lower()
        if v not in ("v4", "v6"):
            raise ValueError("ip_type must be v4 or v6")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return _validate_safe_string(v, "source", max_len=100)

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return _validate_safe_string(v, "notes", max_len=255)


class AssignFirewallRequest(BaseModel):
    firewall_group_id: str = ""

    @field_validator("firewall_group_id")
    @classmethod
    def validate_group_id(cls, v: str) -> str:
        v = v.strip()
        if v == "":
            return v  # empty string = detach
        return _validate_vultr_id(v, "firewall_group_id")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/sync")
async def sync_vpc_report(
    request: Request,
    user: User = Depends(require_permission("vpc.view")),
    session: Session = Depends(get_db_session),
):
    """Trigger a sync of VPC/firewall data from Vultr."""
    runner = request.app.state.ansible_runner
    job = await runner.sync_vpc_report(user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "vpc.sync", "vpc",
               ip_address=_client_ip(request))

    return {"job_id": job.id, "status": job.status}


@router.get("/report")
async def get_vpc_report(
    user: User = Depends(require_permission("vpc.view")),
    session: Session = Depends(get_db_session),
):
    """Return the cached VPC/firewall report, or an empty structure if never synced."""
    report = AppMetadata.get(session, "vpc_report") or dict(EMPTY_REPORT)
    last_synced = AppMetadata.get(session, "vpc_report_time")
    return {
        "vpcs": report.get("vpcs", []),
        "instances": report.get("instances", {}),
        "firewall_groups": report.get("firewall_groups", []),
        "last_synced": last_synced,
    }


@router.post("/vpcs")
async def create_vpc(
    request: Request,
    body: CreateVpcRequest,
    user: User = Depends(require_permission("vpc.manage")),
    session: Session = Depends(get_db_session),
):
    """Create a new VPC."""
    extra_vars = {
        "vpc_description": body.description,
        "vpc_region": body.region,
    }
    if body.v4_subnet:
        extra_vars["vpc_v4_subnet"] = body.v4_subnet
    if body.v4_subnet_mask is not None:
        extra_vars["vpc_v4_subnet_mask"] = body.v4_subnet_mask

    runner = request.app.state.ansible_runner
    job = await runner.run_vpc_playbook(
        "vpc-create.yaml", extra_vars, "vpc-create",
        user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "vpc.create",
               f"vpc/{body.description}",
               details=extra_vars,
               ip_address=_client_ip(request))

    return {"job_id": job.id, "status": job.status}


@router.delete("/vpcs/{vpc_id}")
async def delete_vpc(
    vpc_id: str,
    request: Request,
    user: User = Depends(require_permission("vpc.manage")),
    session: Session = Depends(get_db_session),
):
    """Delete a VPC."""
    vpc_id = _check_path_id(vpc_id, "vpc_id")

    runner = request.app.state.ansible_runner
    job = await runner.run_vpc_playbook(
        "vpc-delete.yaml", {"vpc_id": vpc_id}, "vpc-delete",
        user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "vpc.delete",
               f"vpc/{vpc_id}",
               details={"vpc_id": vpc_id},
               ip_address=_client_ip(request))

    return {"job_id": job.id, "status": job.status}


@router.post("/instances/{instance_id}/attach")
async def attach_vpc(
    instance_id: str,
    request: Request,
    body: VpcIdRequest,
    user: User = Depends(require_permission("vpc.manage")),
    session: Session = Depends(get_db_session),
):
    """Attach a VPC to an instance."""
    instance_id = _check_path_id(instance_id, "instance_id")

    runner = request.app.state.ansible_runner
    job = await runner.run_vpc_playbook(
        "vpc-attach.yaml",
        {"instance_id": instance_id, "vpc_id": body.vpc_id},
        "vpc-attach",
        user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "vpc.attach",
               f"vpc/instances/{instance_id}",
               details={"instance_id": instance_id, "vpc_id": body.vpc_id},
               ip_address=_client_ip(request))

    return {"job_id": job.id, "status": job.status}


@router.post("/instances/{instance_id}/detach")
async def detach_vpc(
    instance_id: str,
    request: Request,
    body: VpcIdRequest,
    user: User = Depends(require_permission("vpc.manage")),
    session: Session = Depends(get_db_session),
):
    """Detach a VPC from an instance."""
    instance_id = _check_path_id(instance_id, "instance_id")

    runner = request.app.state.ansible_runner
    job = await runner.run_vpc_playbook(
        "vpc-detach.yaml",
        {"instance_id": instance_id, "vpc_id": body.vpc_id},
        "vpc-detach",
        user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "vpc.detach",
               f"vpc/instances/{instance_id}",
               details={"instance_id": instance_id, "vpc_id": body.vpc_id},
               ip_address=_client_ip(request))

    return {"job_id": job.id, "status": job.status}


@router.post("/firewall-groups")
async def create_firewall_group(
    request: Request,
    body: CreateFirewallGroupRequest,
    user: User = Depends(require_permission("vpc.manage")),
    session: Session = Depends(get_db_session),
):
    """Create a new firewall group."""
    runner = request.app.state.ansible_runner
    job = await runner.run_vpc_playbook(
        "firewall-group-create.yaml",
        {"group_description": body.description},
        "firewall-group-create",
        user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "vpc.firewall_group.create",
               f"vpc/firewall-groups/{body.description}",
               details={"description": body.description},
               ip_address=_client_ip(request))

    return {"job_id": job.id, "status": job.status}


@router.delete("/firewall-groups/{group_id}")
async def delete_firewall_group(
    group_id: str,
    request: Request,
    user: User = Depends(require_permission("vpc.manage")),
    session: Session = Depends(get_db_session),
):
    """Delete a firewall group."""
    group_id = _check_path_id(group_id, "group_id")

    runner = request.app.state.ansible_runner
    job = await runner.run_vpc_playbook(
        "firewall-group-delete.yaml",
        {"firewall_group_id": group_id},
        "firewall-group-delete",
        user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "vpc.firewall_group.delete",
               f"vpc/firewall-groups/{group_id}",
               details={"firewall_group_id": group_id},
               ip_address=_client_ip(request))

    return {"job_id": job.id, "status": job.status}


@router.post("/firewall-groups/{group_id}/rules")
async def add_firewall_rule(
    group_id: str,
    request: Request,
    body: AddFirewallRuleRequest,
    user: User = Depends(require_permission("vpc.manage")),
    session: Session = Depends(get_db_session),
):
    """Add a rule to a firewall group."""
    group_id = _check_path_id(group_id, "group_id")

    extra_vars = {"firewall_group_id": group_id}
    optional_vars = {
        "rule_protocol": body.protocol,
        "rule_port": body.port,
        "rule_subnet": body.subnet,
        "rule_subnet_size": body.subnet_size,
        "rule_ip_type": body.ip_type,
        "rule_source": body.source,
        "rule_notes": body.notes,
    }
    for key, value in optional_vars.items():
        if value is not None:
            extra_vars[key] = value

    runner = request.app.state.ansible_runner
    job = await runner.run_vpc_playbook(
        "firewall-rule-add.yaml", extra_vars, "firewall-rule-add",
        user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "vpc.firewall_rule.add",
               f"vpc/firewall-groups/{group_id}/rules",
               details=extra_vars,
               ip_address=_client_ip(request))

    return {"job_id": job.id, "status": job.status}


@router.delete("/firewall-groups/{group_id}/rules/{rule_id}")
async def delete_firewall_rule(
    group_id: str,
    rule_id: str,
    request: Request,
    user: User = Depends(require_permission("vpc.manage")),
    session: Session = Depends(get_db_session),
):
    """Delete a rule from a firewall group."""
    group_id = _check_path_id(group_id, "group_id")
    rule_id = rule_id.strip()
    if not rule_id or not re.match(r"^[a-zA-Z0-9\-]+$", rule_id):
        raise HTTPException(status_code=400, detail="rule_id is invalid")

    runner = request.app.state.ansible_runner
    job = await runner.run_vpc_playbook(
        "firewall-rule-delete.yaml",
        {"firewall_group_id": group_id, "rule_id": rule_id},
        "firewall-rule-delete",
        user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "vpc.firewall_rule.delete",
               f"vpc/firewall-groups/{group_id}/rules/{rule_id}",
               details={"firewall_group_id": group_id, "rule_id": rule_id},
               ip_address=_client_ip(request))

    return {"job_id": job.id, "status": job.status}


@router.post("/instances/{instance_id}/firewall")
async def assign_firewall(
    instance_id: str,
    request: Request,
    body: AssignFirewallRequest,
    user: User = Depends(require_permission("vpc.manage")),
    session: Session = Depends(get_db_session),
):
    """Assign a firewall group to an instance (empty firewall_group_id detaches)."""
    instance_id = _check_path_id(instance_id, "instance_id")

    runner = request.app.state.ansible_runner
    job = await runner.run_vpc_playbook(
        "firewall-assign.yaml",
        {"instance_id": instance_id, "firewall_group_id": body.firewall_group_id},
        "firewall-assign",
        user_id=user.id, username=user.username)

    log_action(session, user.id, user.username, "vpc.firewall_assign",
               f"vpc/instances/{instance_id}",
               details={"instance_id": instance_id,
                        "firewall_group_id": body.firewall_group_id or "(detached)"},
               ip_address=_client_ip(request))

    return {"job_id": job.id, "status": job.status}
