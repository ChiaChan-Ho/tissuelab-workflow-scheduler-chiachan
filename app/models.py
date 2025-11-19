from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, List
import uuid


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobType(str, Enum):
    CELL_SEGMENTATION = "CELL_SEGMENTATION"
    TISSUE_MASK = "TISSUE_MASK"


class Job(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    workflow_id: str
    branch: str
    user_id: str
    job_type: JobType
    wsi_path: str
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    error_message: Optional[str] = None


class Workflow(BaseModel):
    workflow_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    user_id: str
    jobs: List[Job] = Field(default_factory=list)


# Request models
class CreateJobRequest(BaseModel):
    branch: str
    job_type: JobType
    wsi_path: str


class CreateWorkflowRequest(BaseModel):
    jobs: List[CreateJobRequest]


# Response models
class JobResponse(BaseModel):
    job_id: str
    workflow_id: str
    branch: str
    user_id: str
    job_type: JobType
    wsi_path: str
    status: JobStatus
    progress: float
    error_message: Optional[str] = None


class WorkflowResponse(BaseModel):
    workflow_id: str
    user_id: str
    jobs: List[JobResponse]
    progress: float  # Overall workflow progress (0-100)
