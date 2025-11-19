from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncio

from .scheduler import scheduler_loop
from .models import (
    CreateWorkflowRequest,
    CreateJobRequest,
    WorkflowResponse,
    JobResponse,
    Workflow,
    Job,
    JobStatus,
)
from .state import (
    add_workflow,
    add_job,
    get_user_workflows,
    get_workflow,
    get_job,
    enqueue_job,
    BRANCH_QUEUES,
    state_lock,
)

app = FastAPI(title="Branch-Aware Workflow Scheduler")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# Dependency to extract X-User-ID header
async def get_current_user_id(request: Request) -> str:
    """Extract X-User-ID from request headers. Return 401 if missing."""
    user_id = request.headers.get("X-User-ID")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    return user_id


# Helper function to convert Job to JobResponse
def job_to_response(job: Job) -> JobResponse:
    """Convert a Job model to JobResponse."""
    return JobResponse(
        job_id=job.job_id,
        workflow_id=job.workflow_id,
        branch=job.branch,
        user_id=job.user_id,
        job_type=job.job_type,
        wsi_path=job.wsi_path,
        status=job.status,
        progress=job.progress,
        error_message=job.error_message,
    )


# Helper function to compute workflow progress
def compute_workflow_progress(workflow: Workflow) -> float:
    """Compute workflow progress as average of job progress."""
    if not workflow.jobs:
        return 0.0
    total_progress = sum(job.progress for job in workflow.jobs)
    return total_progress / len(workflow.jobs)


# Helper function to convert Workflow to WorkflowResponse
def workflow_to_response(workflow: Workflow) -> WorkflowResponse:
    """Convert a Workflow model to WorkflowResponse."""
    return WorkflowResponse(
        workflow_id=workflow.workflow_id,
        user_id=workflow.user_id,
        jobs=[job_to_response(job) for job in workflow.jobs],
        progress=compute_workflow_progress(workflow),
    )


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/workflows", response_model=WorkflowResponse)
async def create_workflow(
    request: CreateWorkflowRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Create a new workflow with jobs."""
    # Create workflow
    workflow = Workflow(user_id=user_id)
    
    # Create jobs for each request
    for job_req in request.jobs:
        job = Job(
            workflow_id=workflow.workflow_id,
            user_id=user_id,
            branch=job_req.branch,
            job_type=job_req.job_type,
            wsi_path=job_req.wsi_path,
            status=JobStatus.PENDING,
            progress=0.0,
        )
        workflow.jobs.append(job)
        # Add job to state
        await add_job(job)
        # Enqueue job to branch queue
        await enqueue_job(job)
    
    # Add workflow to state
    await add_workflow(workflow)
    
    return workflow_to_response(workflow)


@app.get("/workflows", response_model=list[WorkflowResponse])
async def list_workflows(user_id: str = Depends(get_current_user_id)):
    """List all workflows for the current user."""
    workflows = await get_user_workflows(user_id)
    return [workflow_to_response(wf) for wf in workflows]


@app.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow_by_id(
    workflow_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get a specific workflow by ID."""
    workflow = await get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if workflow.user_id != user_id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow_to_response(workflow)


@app.get("/workflows/{workflow_id}/jobs", response_model=list[JobResponse])
async def get_workflow_jobs(
    workflow_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get all jobs in a workflow."""
    workflow = await get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if workflow.user_id != user_id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return [job_to_response(job) for job in workflow.jobs]


@app.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_by_id(
    job_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get a specific job by ID."""
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_to_response(job)


@app.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Cancel a pending job."""
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != JobStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status {job.status}. Only PENDING jobs can be cancelled.",
        )
    
    # Set status to CANCELLED
    job.status = JobStatus.CANCELLED
    
    # Remove from branch queue if present
    async with state_lock:
        if job.branch in BRANCH_QUEUES:
            if job.job_id in BRANCH_QUEUES[job.branch]:
                BRANCH_QUEUES[job.branch].remove(job.job_id)
    
    return job_to_response(job)


@app.get("/workflows/{workflow_id}/progress")
async def get_workflow_progress(
    workflow_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get workflow progress (0-100)."""
    workflow = await get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if workflow.user_id != user_id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    progress = compute_workflow_progress(workflow)
    return {"workflow_id": workflow_id, "progress": progress}


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(scheduler_loop())
