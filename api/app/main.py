from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from api.app.auth import CurrentUser, get_current_user
from shared.config import settings
from shared.db import get_session
from shared.progress import progress_percent_for_stages
from shared.queue import get_queue
from shared.repository import (
    create_job,
    create_project,
    create_run,
    get_project,
    get_run,
    list_jobs_for_runs,
    get_workspace_for_user,
    list_jobs_for_run,
    list_projects,
    list_runs,
    set_job_rq_id,
)
from shared.schemas import ProjectCreate, ProjectOut, RunCreate, RunDetailOut, RunListItemOut, RunStartOut, SnapshotOut, StageOut

app = FastAPI(title="Automated Testing Platform API")
RUN_STAGE_ORDER = ["ingest", "discover"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.api_cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_workspace(session: Session, user: CurrentUser):
    workspace = get_workspace_for_user(session, user.user_id)
    if workspace is None:
        raise HTTPException(status_code=403, detail="Workspace not found for user")
    return workspace


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/projects", response_model=ProjectOut)
def create_project_endpoint(
    payload: ProjectCreate,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> ProjectOut:
    workspace = require_workspace(session, current_user)
    project = create_project(
        session=session,
        workspace_id=workspace.id,
        name=payload.name,
        repo_url=str(payload.repo_url),
        default_branch=payload.default_branch,
    )
    return ProjectOut(
        id=project.id,
        name=project.name,
        repo_url=project.repo_url,
        default_branch=project.default_branch,
        created_at=project.created_at,
    )


@app.get("/projects", response_model=list[ProjectOut])
def list_projects_endpoint(
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[ProjectOut]:
    workspace = require_workspace(session, current_user)
    projects = list_projects(session, workspace.id)
    return [
        ProjectOut(
            id=project.id,
            name=project.name,
            repo_url=project.repo_url,
            default_branch=project.default_branch,
            created_at=project.created_at,
        )
        for project in projects
    ]


@app.post("/projects/{project_id}/runs", response_model=RunStartOut)
def create_run_endpoint(
    project_id: str,
    payload: RunCreate,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> RunStartOut:
    workspace = require_workspace(session, current_user)
    project = get_project(session, project_id, workspace.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    ref_requested = payload.ref or project.default_branch
    run = create_run(session, project=project, ref_requested=ref_requested)
    job = create_job(session, run_id=run.id, stage="ingest")
    create_job(session, run_id=run.id, stage="discover")

    rq_job = get_queue("ingest").enqueue("worker.app.jobs.ingest_job", run.id, job.id)
    set_job_rq_id(session, job.id, rq_job.id)

    return RunStartOut(
        run_id=run.id,
        project_id=run.project_id,
        status=run.status,
        ref_requested=run.ref_requested,
        created_at=run.created_at,
    )


@app.get("/runs", response_model=list[RunListItemOut])
def list_runs_endpoint(
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[RunListItemOut]:
    workspace = require_workspace(session, current_user)
    runs = list_runs(session, workspace.id)
    jobs = list_jobs_for_runs(session, [run.id for run in runs])

    statuses_by_run_id: dict[str, dict[str, str | None]] = {
        run.id: {stage: None for stage in RUN_STAGE_ORDER}
        for run in runs
    }
    for job in jobs:
        if job.run_id in statuses_by_run_id and job.stage in statuses_by_run_id[job.run_id]:
            statuses_by_run_id[job.run_id][job.stage] = job.status

    return [
        RunListItemOut(
            id=run.id,
            project_id=run.project_id,
            project_name=run.project.name,
            status=run.status,
            ref_requested=run.ref_requested,
            ref_resolved=run.ref_resolved,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            progress_percent=progress_percent_for_stages([statuses_by_run_id[run.id][stage] for stage in RUN_STAGE_ORDER]),
        )
        for run in runs
    ]


@app.get("/runs/{run_id}", response_model=RunDetailOut)
def get_run_endpoint(
    run_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> RunDetailOut:
    workspace = require_workspace(session, current_user)
    run = get_run(session, run_id, workspace.id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    jobs = list_jobs_for_run(session, run.id)
    snapshot = None
    if run.snapshot_bucket and run.snapshot_key:
        snapshot = SnapshotOut(
            bucket=run.snapshot_bucket,
            key=run.snapshot_key,
            size_bytes=run.snapshot_size_bytes,
            sha256=run.snapshot_sha256,
        )

    return RunDetailOut(
        id=run.id,
        project_id=run.project_id,
        status=run.status,
        ref_requested=run.ref_requested,
        ref_resolved=run.ref_resolved,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        stages=[
            StageOut(
                stage=job.stage,
                status=job.status,
                started_at=job.started_at,
                finished_at=job.finished_at,
                error_message=job.error_message,
            )
            for job in jobs
        ],
        progress_percent=progress_percent_for_stages(
            [next((job.status for job in jobs if job.stage == stage), None) for stage in RUN_STAGE_ORDER]
        ),
        snapshot=snapshot,
    )
