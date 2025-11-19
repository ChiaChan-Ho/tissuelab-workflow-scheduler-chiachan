# Branch-Aware Multi-Tenant Workflow Scheduler

A lightweight workflow scheduler for Whole Slide Image (WSI) processing tasks, built with FastAPI, featuring branch-aware execution, multi-tenant isolation, and real-time progress monitoring. This implementation integrates a stubbed version of InstanSeg for cell segmentation and tissue mask generation.

## Table of Contents

- [Project Overview](#project-overview)
- [Features](#features)
- [Architecture](#architecture)
- [Setup Instructions](#setup-instructions)
- [Example API Requests](#example-api-requests)
- [Exported Segmentation Results](#exported-segmentation-results)
- [Scaling to 10×](#scaling-to-10)
- [Testing & Monitoring](#testing--monitoring)
- [Demo](#demo)
- [Notes](#notes)
- [License](#license)

## Project Overview

This system provides a minimal workflow orchestration backend for WSI inference workloads.

It supports:

- **Branch-aware execution**: jobs in the same branch run sequentially (FIFO)
- **Parallelism across different branches** (bounded by global worker limit)
- **Multi-tenant isolation** based on `X-User-ID`
- **Active user throttling**: max 3 users with active running jobs
- **Real-time UI updates** via frontend polling
- **WSI tile-based processing** with InstanSeg stubs

All state is held in-memory, making the system simple to run locally.

## Features

- Create workflows containing one or more jobs
- Branch-level serialization + global worker cap
- Multi-tenant isolation with `X-User-ID`
- Live job + workflow progress tracking
- Job cancellation (only when pending)
- JSON result export per job
- Simple HTML/JS frontend included

## Architecture

The system is divided into clear, modular components:

**FastAPI backend**
- REST API for workflows & jobs
- In-memory state store
- Background scheduler loop enforcing branch/user constraints
- Async workers performing WSI tile processing

**Scheduling Logic**
- One running job per branch
- Up to 4 concurrent workers
- Max 3 active users at any time
- Queue-based job dispatch

**Frontend**
- Pure HTML/JS
- Polls backend every 2 seconds
- Displays workflows, jobs, progress, and statuses

This architecture enables predictable execution order while allowing simple parallelism.

## Setup Instructions

### Prerequisites

- Python 3.8+
- macOS or Linux
- `openslide` system library installed

### Installation

```bash
git clone <repository-url>
cd tissuelab-workflow-scheduler-chiachan

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### Install OpenSlide

**macOS:**
```bash
brew install openslide
```

**Ubuntu:**
```bash
sudo apt-get install openslide-tools
```

### Run the backend

```bash
uvicorn app.main:app --reload
```

### Open the UI

- **Frontend**: `http://127.0.0.1:8000/static/index.html`
- **Swagger Docs**: `http://127.0.0.1:8000/docs`

### Quick Start

1. Open the UI
2. Enter user ID (e.g., `user-1`)
3. Create workflow using a real `.svs` file path
4. Observe job progress in real time

## Example API Requests

### Create workflow

```bash
curl -X POST "http://127.0.0.1:8000/workflows" \
  -H "X-User-ID: user-1" \
  -H "Content-Type: application/json" \
  -d '{
    "jobs": [
      {
        "branch": "branch-1",
        "job_type": "CELL_SEGMENTATION",
        "wsi_path": "/path/to/sample.svs"
      }
    ]
  }'
```

### Cancel a pending job

```bash
curl -X POST "http://127.0.0.1:8000/jobs/{job_id}/cancel" \
  -H "X-User-ID: user-1"
```

### Get workflow progress

```bash
curl -H "X-User-ID: user-1" \
  http://127.0.0.1:8000/workflows/{workflow_id}/progress
```

## Exported Segmentation Results

**Note:** The example polygon outputs shown below are illustrative. In this demo implementation, `run_instanseg_on_tile()` returns an empty polygon list (stubbed inference), so exported `{job_id}_cells.json` files will contain `"polygons": []`.

Results are stored under:

```
results/
 ├─ {job_id}_cells.json
 └─ {job_id}_tissue_mask.json
```

### Example cell segmentation output

```json
{
  "job_id": "abc123",
  "polygons": []
}
```

### Example tissue mask output

```json
{
  "job_id": "abc123",
  "tiles": [...]
}
```

Polygon lists are empty in this demo because InstanSeg inference is stubbed.

## Scaling to 10×

To scale this system to production workloads, I would:

- Move in-memory state to Redis (queues + locks) and PostgreSQL (persistent job/workflow storage)
- Run the scheduler as a stateless service, using Redis locks for coordination
- Offload job execution to a distributed worker pool (Celery / RQ)
- Containerize API + workers and run under Kubernetes, enabling horizontal auto-scaling
- Add Prometheus metrics (queue depth, worker load, job latency) and Grafana dashboards
- Add caching + rate limiting for high-throughput environments

## Testing & Monitoring

### Testing

- Use FastAPI `TestClient` for endpoint tests
- Unit test scheduler constraints (branch serialization, active user limit, worker limit)
- Integration test workflow creation, progress polling, and cancellation

### Monitoring

- Log job lifecycle transitions (`PENDING → RUNNING → SUCCEEDED/FAILED`)
- Track metrics such as:
  - queue depth per branch
  - active users
  - job latency
  - worker utilization

In production, these would be surfaced via Prometheus/Grafana.

## Demo

Screenshots are available in the `/screenshots` directory:

- `01_set_user.png` — Setting the user
- `02_create_workflow.png` — Creating workflow
- `03_running_workflow.png` — Live job updates
- `04_completed_and_results.png` — Completed job + exported results

## Notes

- InstanSeg inference is stubbed in this implementation
- WSI samples used for testing can be downloaded from:
  - https://openslide.cs.cmu.edu/download/openslide-testdata/Aperio/
- All state is in-memory and resets on server restart

## License

This project was created as part of a take-home engineering challenge.
