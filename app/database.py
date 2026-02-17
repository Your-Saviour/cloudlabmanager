import json
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, Text, DateTime,
    ForeignKey, Index, Table, event, text, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

DB_PATH = "/data/cloudlab.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Enable WAL mode for better concurrent read performance
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


# --- Association tables ---

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

object_tags = Table(
    "object_tags",
    Base.metadata,
    Column("object_id", Integer, ForeignKey("inventory_objects.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("inventory_tags.id", ondelete="CASCADE"), primary_key=True),
)


# --- Models ---

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(30), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    display_name = Column(String(100), nullable=True)
    password_hash = Column(String(255), nullable=True)  # null until invite accepted
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    invited_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    invite_accepted_at = Column(DateTime(timezone=True), nullable=True)
    ssh_public_key = Column(Text, nullable=True)

    roles = relationship("Role", secondary=user_roles, back_populates="users", lazy="selectin")
    invited_by = relationship("User", remote_side="User.id", foreign_keys=[invited_by_id])


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    is_system = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles", lazy="selectin")
    users = relationship("User", secondary=user_roles, back_populates="roles", lazy="selectin")


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codename = Column(String(100), unique=True, nullable=False, index=True)
    category = Column(String(50), nullable=False)
    label = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)

    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")


class InviteToken(Base):
    __tablename__ = "invite_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")


class UserMFA(Base):
    __tablename__ = "user_mfa"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    is_enabled = Column(Boolean, default=False, nullable=False)
    totp_secret_encrypted = Column(Text, nullable=True)  # Fernet-encrypted TOTP secret
    enrolled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    user = relationship("User")


class MFABackupCode(Base):
    __tablename__ = "mfa_backup_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(255), nullable=False)  # bcrypt hash of the backup code
    is_used = Column(Boolean, default=False, nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    preferences = Column(Text, nullable=False, default="{}")  # JSON blob
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username = Column(String(30), nullable=True)
    action = Column(String(100), nullable=False)
    resource = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)  # JSON text
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class ConfigVersion(Base):
    __tablename__ = "config_versions"
    __table_args__ = (
        Index('ix_config_versions_lookup', 'service_name', 'filename', 'version_number'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_name = Column(String(100), nullable=False, index=True)
    filename = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    version_number = Column(Integer, nullable=False)
    change_note = Column(String(500), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_username = Column(String(30), nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    creator = relationship("User", foreign_keys=[created_by_id])


class AppMetadata(Base):
    __tablename__ = "app_metadata"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)  # JSON text

    @classmethod
    def get(cls, session, key, default=None):
        row = session.query(cls).filter_by(key=key).first()
        if row is None:
            return default
        try:
            return json.loads(row.value)
        except (json.JSONDecodeError, TypeError):
            return row.value

    @classmethod
    def set(cls, session, key, value):
        row = session.query(cls).filter_by(key=key).first()
        serialized = json.dumps(value) if not isinstance(value, str) else json.dumps(value)
        if row:
            row.value = serialized
        else:
            session.add(cls(key=key, value=serialized))
        session.flush()


class JobRecord(Base):
    __tablename__ = "jobs"

    id = Column(String(20), primary_key=True)
    service = Column(String(100), nullable=False)
    action = Column(String(50), nullable=False)
    script = Column(String(100), nullable=True)
    status = Column(String(20), default="running", nullable=False)
    started_at = Column(String(50), nullable=True)
    finished_at = Column(String(50), nullable=True)
    output = Column(Text, nullable=True)  # JSON array text
    deployment_id = Column(String(100), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username = Column(String(30), nullable=True)
    object_id = Column(Integer, ForeignKey("inventory_objects.id", ondelete="SET NULL"), nullable=True)
    type_slug = Column(String(50), nullable=True)
    schedule_id = Column(Integer, ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    inputs = Column(Text, nullable=True)  # JSON dict of original inputs
    parent_job_id = Column(String(20), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    webhook_id = Column(Integer, ForeignKey("webhook_endpoints.id", ondelete="SET NULL"), nullable=True)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)

    # What to run
    job_type = Column(String(30), nullable=False)  # "service_script", "inventory_action", "system_task"

    # For service_script: service name + script name
    service_name = Column(String(100), nullable=True)
    script_name = Column(String(100), nullable=True)

    # For inventory_action: type_slug + action_name + object_id
    type_slug = Column(String(50), nullable=True)
    action_name = Column(String(100), nullable=True)
    object_id = Column(Integer, ForeignKey("inventory_objects.id", ondelete="SET NULL"), nullable=True)

    # For system_task: task identifier (e.g., "refresh_instances", "refresh_costs")
    system_task = Column(String(50), nullable=True)

    # Schedule
    cron_expression = Column(String(100), nullable=False)  # Standard 5-field cron
    is_enabled = Column(Boolean, default=True, nullable=False)

    # Inputs (JSON dict, passed as env vars for scripts)
    inputs = Column(Text, nullable=True)  # JSON dict

    # Execution tracking
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_job_id = Column(String(20), nullable=True)  # FK to jobs.id conceptually
    last_status = Column(String(20), nullable=True)  # "completed", "failed", "running"
    next_run_at = Column(DateTime(timezone=True), nullable=True)

    # Overlap policy
    skip_if_running = Column(Boolean, default=True, nullable=False)

    # Ownership & audit
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    inventory_object = relationship("InventoryObject", foreign_keys=[object_id])


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    token = Column(String(64), unique=True, nullable=False, index=True)

    # Target action (same 3 types as ScheduledJob)
    job_type = Column(String(30), nullable=False)  # "service_script", "inventory_action", "system_task"
    service_name = Column(String(100), nullable=True)
    script_name = Column(String(100), nullable=True)
    type_slug = Column(String(50), nullable=True)
    action_name = Column(String(100), nullable=True)
    object_id = Column(Integer, ForeignKey("inventory_objects.id", ondelete="SET NULL"), nullable=True)
    system_task = Column(String(50), nullable=True)

    # Payload mapping: JSON dict of {"input_name": "$.jsonpath.expression"}
    payload_mapping = Column(Text, nullable=True)

    # State
    is_enabled = Column(Boolean, default=True, nullable=False)
    last_trigger_at = Column(DateTime(timezone=True), nullable=True)
    last_job_id = Column(String(20), nullable=True)
    last_status = Column(String(20), nullable=True)
    trigger_count = Column(Integer, default=0, nullable=False)

    # Ownership & audit
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    inventory_object = relationship("InventoryObject", foreign_keys=[object_id])


# --- Inventory models ---

class InventoryType(Base):
    __tablename__ = "inventory_types"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(50), unique=True, nullable=False)
    label = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    icon = Column(String(50), nullable=True)
    config_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    objects = relationship("InventoryObject", back_populates="type", cascade="all, delete-orphan")


class InventoryObject(Base):
    __tablename__ = "inventory_objects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type_id = Column(Integer, ForeignKey("inventory_types.id", ondelete="CASCADE"), nullable=False)
    data = Column(Text, nullable=False)  # JSON blob of field values
    search_text = Column(Text, nullable=True)  # denormalized searchable text
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    type = relationship("InventoryType", back_populates="objects")
    tags = relationship("InventoryTag", secondary=object_tags, back_populates="objects")
    acl_rules = relationship("ObjectACL", back_populates="object", cascade="all, delete-orphan")


class InventoryTag(Base):
    __tablename__ = "inventory_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    color = Column(String(7), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    objects = relationship("InventoryObject", secondary=object_tags, back_populates="tags")
    permissions = relationship("TagPermission", back_populates="tag", cascade="all, delete-orphan")


class ObjectACL(Base):
    __tablename__ = "object_acl"

    id = Column(Integer, primary_key=True, autoincrement=True)
    object_id = Column(Integer, ForeignKey("inventory_objects.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission = Column(String(50), nullable=False)  # "view", "edit", "deploy", etc.
    effect = Column(String(5), nullable=False)  # "allow" or "deny"

    object = relationship("InventoryObject", back_populates="acl_rules")
    role = relationship("Role")


class ServiceACL(Base):
    __tablename__ = "service_acl"
    __table_args__ = (
        UniqueConstraint("service_name", "role_id", "permission", name="uq_service_acl"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_name = Column(String(100), nullable=False, index=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission = Column(String(20), nullable=False)  # "view", "deploy", "stop", "config"
    created_at = Column(DateTime(timezone=True), default=utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    role = relationship("Role")
    creator = relationship("User", foreign_keys=[created_by])


class TagPermission(Base):
    __tablename__ = "tag_permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_id = Column(Integer, ForeignKey("inventory_tags.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission = Column(String(50), nullable=False)

    tag = relationship("InventoryTag", back_populates="permissions")
    role = relationship("Role")


class DriftReport(Base):
    __tablename__ = "drift_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(20), nullable=False)  # "clean", "drifted", "error"
    previous_status = Column(String(20), nullable=True)  # for transition detection
    summary = Column(Text, nullable=False)  # JSON: counts of in_sync, drifted, missing, orphaned
    report_data = Column(Text, nullable=False)  # Full JSON report from Ansible playbook
    checked_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    triggered_by = Column(String(50), nullable=True)  # "poller", "manual", "schedule"
    error_message = Column(Text, nullable=True)


class HealthCheckResult(Base):
    __tablename__ = "health_check_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_name = Column(String(100), nullable=False, index=True)
    check_name = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False)  # "healthy", "unhealthy", "degraded", "unknown"
    previous_status = Column(String(20), nullable=True)  # for transition detection
    response_time_ms = Column(Integer, nullable=True)  # response time in milliseconds
    status_code = Column(Integer, nullable=True)  # HTTP status code if applicable
    error_message = Column(Text, nullable=True)  # error details if unhealthy
    checked_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    check_type = Column(String(20), nullable=False)  # "http", "tcp", "icmp", "ssh_command"
    target = Column(String(255), nullable=True)  # URL or host:port that was checked


class PortalBookmark(Base):
    __tablename__ = "portal_bookmarks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    service_name = Column(String(100), nullable=False)
    label = Column(String(200), nullable=False)
    url = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User")


class CostSnapshot(Base):
    __tablename__ = "cost_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    total_monthly_cost = Column(String(20), nullable=False)  # stored as string like Ansible does
    instance_count = Column(Integer, nullable=False, default=0)
    snapshot_data = Column(Text, nullable=False)  # Full JSON: instances with per-instance costs
    source = Column(String(20), nullable=False)  # "playbook" or "computed"
    captured_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vultr_snapshot_id = Column(String(50), unique=True, nullable=False, index=True)
    instance_vultr_id = Column(String(50), nullable=True)  # Vultr instance ID it was taken from
    instance_label = Column(String(200), nullable=True)     # Human-readable instance name at time of snapshot
    description = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # "pending", "complete", "failed"
    size_gb = Column(Integer, nullable=True)                # Size in GB (populated after completion)
    os_id = Column(Integer, nullable=True)                  # Vultr OS ID
    app_id = Column(Integer, nullable=True)                 # Vultr App ID
    vultr_created_at = Column(String(50), nullable=True)    # Vultr's creation timestamp (string)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_username = Column(String(30), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    creator = relationship("User", foreign_keys=[created_by])


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_type = Column(String(20), nullable=False)  # "slack", "email" (future extensibility)
    name = Column(String(100), nullable=False)          # e.g. "Main Slack Channel"
    config = Column(Text, nullable=False)               # JSON: {"webhook_url": "https://..."} for Slack
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    event_type = Column(String(50), nullable=False)       # "job.completed", "job.failed", "health.state_change", "schedule.completed", "schedule.failed"
    channel = Column(String(20), nullable=False)           # "in_app", "email", "slack"
    channel_id = Column(Integer, ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=True)  # NULL for in_app/email
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    filters = Column(Text, nullable=True)                  # JSON: {"service_name": "n8n-server", "status": "failed"} — optional filters
    is_enabled = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False, server_default="0")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    role = relationship("Role")
    notification_channel = relationship("NotificationChannel")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    event_type = Column(String(50), nullable=False)       # same event_type as rules
    severity = Column(String(20), default="info", nullable=False)  # "info", "success", "warning", "error"
    action_url = Column(String(500), nullable=True)       # e.g. "/jobs/abc123" — frontend route to navigate to
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    user = relationship("User")


class BugReport(Base):
    __tablename__ = "bug_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(200), nullable=False)
    steps_to_reproduce = Column(Text, nullable=False)
    expected_vs_actual = Column(Text, nullable=False)
    severity = Column(String(20), default="medium", nullable=False)  # low, medium, high, critical
    page_url = Column(String(500), nullable=True)
    browser_info = Column(String(500), nullable=True)
    screenshot_path = Column(String(500), nullable=True)  # relative path within /data/persistent/feedback/
    status = Column(String(20), default="new", nullable=False)  # new, investigating, fixed, wont-fix, duplicate
    admin_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User")


class FeedbackRequest(Base):
    __tablename__ = "feedback_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(20), nullable=False, index=True)  # "feature_request" | "bug_report"
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    priority = Column(String(20), default="medium", nullable=False)  # "low" | "medium" | "high"
    screenshot_path = Column(String(500), nullable=True)
    status = Column(String(20), default="new", nullable=False, index=True)  # "new" | "reviewed" | "planned" | "in_progress" | "completed" | "declined"
    admin_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", lazy="selectin")


def create_tables():
    Base.metadata.create_all(bind=engine)
    # Migration: add new columns if missing (idempotent)
    migrations = [
        "ALTER TABLE users ADD COLUMN ssh_public_key TEXT",
        "ALTER TABLE jobs ADD COLUMN object_id INTEGER REFERENCES inventory_objects(id) ON DELETE SET NULL",
        "ALTER TABLE jobs ADD COLUMN type_slug VARCHAR(50)",
        "ALTER TABLE jobs ADD COLUMN schedule_id INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL",
        "ALTER TABLE health_check_results ADD COLUMN previous_status VARCHAR(20)",
        "ALTER TABLE drift_reports ADD COLUMN previous_status VARCHAR(20)",
        "ALTER TABLE jobs ADD COLUMN inputs TEXT",
        "ALTER TABLE jobs ADD COLUMN parent_job_id VARCHAR(20) REFERENCES jobs(id) ON DELETE SET NULL",
        "ALTER TABLE jobs ADD COLUMN webhook_id INTEGER REFERENCES webhook_endpoints(id) ON DELETE SET NULL",
        "ALTER TABLE users ADD COLUMN email VARCHAR(255)",
        "ALTER TABLE notification_rules ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                conn.rollback()
