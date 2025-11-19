import asyncio
from typing import Dict, List, Set, Optional

from .models import Workflow, Job


# Global state structures
WORKFLOWS: Dict[str, Workflow] = {}
JOBS: Dict[str, Job] = {}
BRANCH_QUEUES: Dict[str, List[str]] = {}  # branch name -> [job_id, ...] in FIFO order
RUNNING_JOBS: Set[str] = set()  # job_ids currently running
ACTIVE_USERS: Set[str] = set()  # user_ids that currently have at least one RUNNING job
USER_QUEUE: List[str] = []  # user_ids waiting for a free active-user slot

# Lock to protect all shared state
state_lock = asyncio.Lock()


async def add_workflow(workflow: Workflow) -> None:
    """Add a workflow to the global state."""
    async with state_lock:
        WORKFLOWS[workflow.workflow_id] = workflow
        # Also add all jobs from the workflow
        for job in workflow.jobs:
            JOBS[job.job_id] = job


async def add_job(job: Job) -> None:
    """Add a job to the global state."""
    async with state_lock:
        JOBS[job.job_id] = job
        # Add job to its workflow's jobs list if workflow exists
        if job.workflow_id in WORKFLOWS:
            workflow = WORKFLOWS[job.workflow_id]
            # Check if job is already in the list
            if not any(j.job_id == job.job_id for j in workflow.jobs):
                workflow.jobs.append(job)


async def get_user_workflows(user_id: str) -> List[Workflow]:
    """Get all workflows for a specific user."""
    async with state_lock:
        return [wf for wf in WORKFLOWS.values() if wf.user_id == user_id]


async def get_workflow(workflow_id: str) -> Optional[Workflow]:
    """Get a workflow by ID."""
    async with state_lock:
        return WORKFLOWS.get(workflow_id)


async def get_job(job_id: str) -> Optional[Job]:
    """Get a job by ID."""
    async with state_lock:
        return JOBS.get(job_id)


async def enqueue_job(job: Job) -> None:
    """Add a job to its branch queue (FIFO order)."""
    async with state_lock:
        if job.branch not in BRANCH_QUEUES:
            BRANCH_QUEUES[job.branch] = []
        BRANCH_QUEUES[job.branch].append(job.job_id)

