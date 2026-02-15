import re
from pydantic import BaseModel, field_validator, Field
from typing import Optional, Any
from datetime import datetime

MAX_BULK_ITEMS = 100


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Optional[dict] = None
    permissions: list[str] = []


class SetupRequest(BaseModel):
    username: str
    password: str
    vault_password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if not re.match(r"^[a-zA-Z0-9_]{3,30}$", v):
            raise ValueError("Username must be 3-30 alphanumeric characters or underscores")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class Instance(BaseModel):
    hostname: str
    ip: Optional[str] = None
    region: Optional[str] = None
    plan: Optional[str] = None
    tags: list[str] = []
    power_status: Optional[str] = None
    vultr_id: Optional[str] = None


class Service(BaseModel):
    name: str
    filename: str


class Job(BaseModel):
    id: str
    service: str
    action: str
    script: Optional[str] = None
    status: str = "running"
    started_at: str = ""
    finished_at: Optional[str] = None
    output: list[str] = []
    deployment_id: Optional[str] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
    schedule_id: Optional[int] = None
    inputs: Optional[dict] = None
    parent_job_id: Optional[str] = None


# --- New models for RBAC ---

class InviteUserRequest(BaseModel):
    username: str
    email: str
    display_name: Optional[str] = None
    role_ids: list[int] = []

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if not re.match(r"^[a-zA-Z0-9_]{3,30}$", v):
            raise ValueError("Username must be 3-30 alphanumeric characters or underscores")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email format")
        return v.lower()


class AcceptInviteRequest(BaseModel):
    token: str
    password: str
    display_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirm(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("New password must be at least 8 characters")
        return v


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if v is not None and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email format")
        return v.lower() if v else v


class RoleCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    permission_ids: list[int] = []

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not 2 <= len(v) <= 50:
            raise ValueError("Role name must be 2-50 characters")
        return v


class RoleUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permission_ids: Optional[list[int]] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if v is not None and not 2 <= len(v) <= 50:
            raise ValueError("Role name must be 2-50 characters")
        return v


class UserRoleAssignment(BaseModel):
    role_ids: list[int]


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if v is not None and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email format")
        return v.lower() if v else v


# --- Inventory models ---

class InventoryObjectCreate(BaseModel):
    data: dict[str, Any]
    tag_ids: list[int] = []

class InventoryObjectUpdate(BaseModel):
    data: Optional[dict[str, Any]] = None
    tag_ids: Optional[list[int]] = None

class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not 1 <= len(v.strip()) <= 100:
            raise ValueError("Tag name must be 1-100 characters")
        return v.strip()

class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None

class ACLRuleCreate(BaseModel):
    role_id: int
    permission: str
    effect: str = "allow"

    @field_validator("effect")
    @classmethod
    def validate_effect(cls, v):
        if v not in ("allow", "deny"):
            raise ValueError("Effect must be 'allow' or 'deny'")
        return v

class TagPermissionSet(BaseModel):
    role_id: int
    permission: str

class ObjectTagsUpdate(BaseModel):
    tag_ids: list[int]


# --- Bulk operation models ---

class BulkServiceActionRequest(BaseModel):
    """Request for bulk service operations (stop, deploy)."""
    service_names: list[str] = Field(max_length=MAX_BULK_ITEMS)

    @field_validator("service_names")
    @classmethod
    def validate_service_names(cls, v):
        for name in v:
            if not re.match(r"^[a-zA-Z0-9_-]{1,100}$", name):
                raise ValueError(f"Invalid service name: {name}")
        return v

class BulkInventoryDeleteRequest(BaseModel):
    """Request for bulk delete of inventory objects."""
    object_ids: list[int] = Field(max_length=MAX_BULK_ITEMS)

class BulkInventoryTagRequest(BaseModel):
    """Request for bulk tag add/remove on inventory objects."""
    object_ids: list[int] = Field(max_length=MAX_BULK_ITEMS)
    tag_ids: list[int] = Field(max_length=MAX_BULK_ITEMS)

class BulkInventoryActionRequest(BaseModel):
    """Request for bulk action execution on inventory objects."""
    object_ids: list[int] = Field(max_length=MAX_BULK_ITEMS)

class BulkActionResult(BaseModel):
    """Response for bulk operations with partial success support."""
    job_id: str | None = None
    succeeded: list[str] = []
    skipped: list[dict] = []  # [{"name": "...", "reason": "..."}]
    total: int = 0


# --- Scheduled job models ---

class ScheduledJobCreate(BaseModel):
    name: str
    description: Optional[str] = None
    job_type: str  # "service_script", "inventory_action", "system_task"
    service_name: Optional[str] = None
    script_name: Optional[str] = None
    type_slug: Optional[str] = None
    action_name: Optional[str] = None
    object_id: Optional[int] = None
    system_task: Optional[str] = None
    cron_expression: str
    is_enabled: bool = True
    inputs: Optional[dict[str, Any]] = None
    skip_if_running: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not 1 <= len(v.strip()) <= 100:
            raise ValueError("Name must be 1-100 characters")
        return v.strip()

    @field_validator("job_type")
    @classmethod
    def validate_job_type(cls, v):
        if v not in ("service_script", "inventory_action", "system_task"):
            raise ValueError("job_type must be 'service_script', 'inventory_action', or 'system_task'")
        return v


class ScheduledJobUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cron_expression: Optional[str] = None
    is_enabled: Optional[bool] = None
    inputs: Optional[dict[str, Any]] = None
    skip_if_running: Optional[bool] = None


# --- Notification models ---

class NotificationOut(BaseModel):
    id: int
    title: str
    body: Optional[str]
    event_type: str
    severity: str
    action_url: Optional[str]
    is_read: bool
    created_at: str


class NotificationCountOut(BaseModel):
    unread: int


class NotificationRuleCreate(BaseModel):
    name: str
    event_type: str
    channel: str           # "in_app", "email", "slack"
    channel_id: Optional[int] = None
    role_id: int
    filters: Optional[dict] = None
    is_enabled: bool = True


class NotificationRuleUpdate(BaseModel):
    name: Optional[str] = None
    event_type: Optional[str] = None
    channel: Optional[str] = None
    channel_id: Optional[int] = None
    role_id: Optional[int] = None
    filters: Optional[dict] = None
    is_enabled: Optional[bool] = None


class NotificationRuleOut(BaseModel):
    id: int
    name: str
    event_type: str
    channel: str
    channel_id: Optional[int]
    role_id: int
    role_name: Optional[str] = None
    filters: Optional[dict]
    is_enabled: bool
    created_at: str


class NotificationChannelCreate(BaseModel):
    channel_type: str      # "slack"
    name: str
    config: dict           # {"webhook_url": "https://hooks.slack.com/..."}
    is_enabled: bool = True


class NotificationChannelOut(BaseModel):
    id: int
    channel_type: str
    name: str
    config: dict
    is_enabled: bool
    created_at: str
