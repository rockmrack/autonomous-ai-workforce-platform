"""
Core database models and base classes
Enhanced with advanced features like soft delete, versioning, and audit trails
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class BaseModel(AsyncAttrs, DeclarativeBase):
    """
    Base model with common functionality for all database models.

    Features:
    - UUID primary keys for security and distribution
    - Automatic timestamps
    - Soft delete support
    - JSON metadata storage
    - Version tracking for optimistic locking
    """

    __abstract__ = True

    # Use UUID for all primary keys
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )

    # Automatic timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Soft delete support
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True,
    )

    # Version for optimistic locking
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    # Flexible metadata storage
    metadata_json: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )

    @declared_attr.directive
    @classmethod
    def __tablename__(cls) -> str:
        """Auto-generate table name from class name"""
        # Convert CamelCase to snake_case
        name = cls.__name__
        return "".join(
            ["_" + c.lower() if c.isupper() else c for c in name]
        ).lstrip("_")

    def soft_delete(self) -> None:
        """Mark record as deleted without removing from database"""
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()

    def restore(self) -> None:
        """Restore a soft-deleted record"""
        self.is_deleted = False
        self.deleted_at = None

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary"""
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
            if not column.name.startswith("_")
        }

    def update_from_dict(self, data: dict[str, Any]) -> None:
        """Update model fields from dictionary"""
        for key, value in data.items():
            if hasattr(self, key) and not key.startswith("_"):
                setattr(self, key, value)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id})>"


class TimestampMixin:
    """Mixin for models that only need timestamps without full BaseModel"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class AuditMixin:
    """Mixin for models that need audit trail"""

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    audit_log: Mapped[Optional[list]] = mapped_column(
        JSONB,
        nullable=True,
        default=list,
    )

    def add_audit_entry(
        self,
        action: str,
        user_id: Optional[uuid.UUID] = None,
        details: Optional[dict] = None,
    ) -> None:
        """Add an entry to the audit log"""
        if self.audit_log is None:
            self.audit_log = []

        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "user_id": str(user_id) if user_id else None,
            "details": details or {},
        }
        self.audit_log.append(entry)


class TaggableMixin:
    """Mixin for models that can be tagged"""

    tags: Mapped[Optional[list]] = mapped_column(
        JSONB,
        nullable=True,
        default=list,
    )

    def add_tag(self, tag: str) -> None:
        """Add a tag"""
        if self.tags is None:
            self.tags = []
        if tag not in self.tags:
            self.tags.append(tag)

    def remove_tag(self, tag: str) -> None:
        """Remove a tag"""
        if self.tags and tag in self.tags:
            self.tags.remove(tag)

    def has_tag(self, tag: str) -> bool:
        """Check if has a specific tag"""
        return self.tags is not None and tag in self.tags


# Event listeners for automatic version incrementing
@event.listens_for(BaseModel, "before_update", propagate=True)
def increment_version(mapper: Any, connection: Any, target: BaseModel) -> None:
    """Automatically increment version on update"""
    target.version += 1
