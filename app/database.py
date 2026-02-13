import json
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, Text, DateTime,
    ForeignKey, Table, event, text,
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


class TagPermission(Base):
    __tablename__ = "tag_permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_id = Column(Integer, ForeignKey("inventory_tags.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission = Column(String(50), nullable=False)

    tag = relationship("InventoryTag", back_populates="permissions")
    role = relationship("Role")


def create_tables():
    Base.metadata.create_all(bind=engine)
    # Migration: add new columns if missing (idempotent)
    migrations = [
        "ALTER TABLE users ADD COLUMN ssh_public_key TEXT",
        "ALTER TABLE jobs ADD COLUMN object_id INTEGER REFERENCES inventory_objects(id) ON DELETE SET NULL",
        "ALTER TABLE jobs ADD COLUMN type_slug VARCHAR(50)",
        "ALTER TABLE jobs ADD COLUMN schedule_id INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                conn.rollback()
