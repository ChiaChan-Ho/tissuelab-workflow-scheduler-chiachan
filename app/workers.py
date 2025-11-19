import asyncio

from .models import Job, JobStatus, JobType
from .state import RUNNING_JOBS, state_lock
from .instanseg_tasks import instanseg_process_wsi, generate_tissue_mask


async def run_job(job: Job):
    """Execute a job, updating progress and status."""
    try:
        if job.job_type == JobType.CELL_SEGMENTATION:
            await instanseg_process_wsi(job, job.wsi_path)
        elif job.job_type == JobType.TISSUE_MASK:
            await generate_tissue_mask(job, job.wsi_path)
        else:
            # Unknown type – fail the job
            job.status = JobStatus.FAILED
            job.error_message = f"Unsupported job type: {job.job_type}"
            return

        # If we get here without exception, mark as succeeded (the task functions should set progress to 100%)
        if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
            job.status = JobStatus.SUCCEEDED
            job.progress = 100.0
    except Exception as e:
        job.status = JobStatus.FAILED
        job.error_message = str(e)
    finally:
        async with state_lock:
            if job.job_id in RUNNING_JOBS:
                RUNNING_JOBS.remove(job.job_id)
