import asyncio

from .state import BRANCH_QUEUES, RUNNING_JOBS, JOBS, state_lock
from .models import JobStatus
from .workers import run_job

# Constants
MAX_WORKERS = 4  # max number of concurrent running jobs
ACTIVE_USERS_LIMIT = 3  # max number of distinct users with RUNNING jobs


async def scheduler_loop():
    """Main scheduling loop that enforces branch-aware scheduling and user limits."""
    while True:
        await asyncio.sleep(0.1)  # small delay between scheduling cycles

        async with state_lock:
            # If no pending jobs, just continue
            if not BRANCH_QUEUES:
                continue

            # Recompute active users from running jobs
            current_active_users = set()
            for job_id in RUNNING_JOBS:
                job = JOBS.get(job_id)
                if job:
                    current_active_users.add(job.user_id)

            # If we already have max workers, skip this cycle
            if len(RUNNING_JOBS) >= MAX_WORKERS:
                continue

            # Iterate over branches and look at the head of each queue (FIFO)
            jobs_to_start = []
            for branch, queue in BRANCH_QUEUES.items():
                if not queue:
                    continue

                # Enforce "serial per branch": if any running job has this branch, skip
                branch_busy = False
                for running_id in RUNNING_JOBS:
                    running_job = JOBS.get(running_id)
                    if running_job and running_job.branch == branch:
                        branch_busy = True
                        break
                if branch_busy:
                    continue

                # Peek the next job in this branch
                next_job_id = queue[0]
                job = JOBS.get(next_job_id)
                if not job:
                    # Clean up bad ids
                    queue.pop(0)
                    continue

                # Only consider PENDING jobs
                if job.status != JobStatus.PENDING:
                    queue.pop(0)
                    continue

                # Enforce max 3 active users:
                # - If this job's user is new AND we already have 3 active users, skip it for now.
                if job.user_id not in current_active_users and len(current_active_users) >= ACTIVE_USERS_LIMIT:
                    continue

                # Enforce global worker limit
                if len(RUNNING_JOBS) >= MAX_WORKERS:
                    break

                # This job can be started
                jobs_to_start.append((branch, job))

            # Now actually start the selected jobs
            for branch, job in jobs_to_start:
                # Double-check limits again
                if len(RUNNING_JOBS) >= MAX_WORKERS:
                    break

                # Update state: mark job as RUNNING, remove from branch queue, track in RUNNING_JOBS
                job.status = JobStatus.RUNNING
                if BRANCH_QUEUES.get(branch) and BRANCH_QUEUES[branch][0] == job.job_id:
                    BRANCH_QUEUES[branch].pop(0)
                RUNNING_JOBS.add(job.job_id)

                # Update active users set for this scheduling cycle
                current_active_users.add(job.user_id)

                # Start the worker task outside the lock
                asyncio.create_task(run_job(job))
