import uuid

from datetime import datetime
from typing import Literal
from enum import Enum
from sqlmodel import Field, SQLModel
from app.models.user import User

class Image(SQLModel, table=True):
    __tablename__ = "images"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(nullable=False, index=True, max_length=30) # TODO: tell the user the character constraints
    size: int = Field(nullable=False)
    content_type: str = Field(nullable=False)
    url: str = Field(nullable=False)
    uploaded_by: int = Field(nullable=False, foreign_key="users.id")  # Reference to User.id


class JobStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class TransformJob(SQLModel, table=True):
    __tablename__ = "transform_jobs"  
    job_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: int = Field(nullable=False, index=True)
    given_image_id: uuid.UUID | None = Field(default=None, index=True)
    transform_image_id: uuid.UUID | None = Field(default=None, index=True)
    status: JobStatus
    error_message: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)