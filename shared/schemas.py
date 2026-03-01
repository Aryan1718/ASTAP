from datetime import datetime
from typing import Optional

from pydantic import BaseModel, HttpUrl


class ProjectCreate(BaseModel):
    name: str
    repo_url: HttpUrl
    default_branch: str = "main"


class ProjectOut(BaseModel):
    id: str
    name: str
    repo_url: str
    default_branch: str
    created_at: datetime


class RunCreate(BaseModel):
    ref: Optional[str] = None


class RunStartOut(BaseModel):
    run_id: str
    project_id: str
    status: str
    ref_requested: str
    created_at: datetime


class RunListItemOut(BaseModel):
    id: str
    project_id: str
    project_name: str
    status: str
    ref_requested: str
    ref_resolved: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    progress_percent: int


class StageOut(BaseModel):
    stage: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None


class SnapshotOut(BaseModel):
    bucket: str
    key: str
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None


class RunDetailOut(BaseModel):
    id: str
    project_id: str
    status: str
    ref_requested: str
    ref_resolved: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    stages: list[StageOut]
    progress_percent: int
    snapshot: Optional[SnapshotOut] = None
