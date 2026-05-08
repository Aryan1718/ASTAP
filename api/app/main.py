from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from api.app.analysis_results import AnalysisResultsService
from api.app.auth import CurrentUser, get_current_user
from api.app.execution_results import ExecutionResultsService
from api.app.generated_tests import GeneratedTestsService
from shared.config import settings
from shared.db import get_session
from shared.progress import progress_percent_for_stages
from shared.queue import get_queue
from shared.repository import (
    create_project,
    create_job,
    create_run,
    delete_project,
    get_project,
    get_run,
    get_workspace_for_user,
    list_jobs_for_run,
    list_jobs_for_runs,
    list_projects,
    list_runs,
    set_job_rq_id,
)
from shared.schemas import (
    GeneratedTestFileContentResponse,
    GeneratedTestCasesResponse,
    GeneratedTestManifestOut,
    GeneratedTestTreeResponse,
    ExecutionLogOut,
    ExecutionSummaryOut,
    AnalysisReportOut,
    AnalysisSummaryOut,
    ProjectCreate,
    ProjectOut,
    RunCreate,
    RunDetailOut,
    RunListItemOut,
    RunStartOut,
    SnapshotOut,
    StageOut,
)

app = FastAPI(title="Automated Testing Platform API")
RUN_STAGE_ORDER = ["ingest", "discover", "generate_tests", "execute_tests", "analyze"]
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


@app.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_endpoint(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> Response:
    workspace = require_workspace(session, current_user)
    deleted = delete_project(session, project_id, workspace.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    create_job(session, run_id=run.id, stage="generate_tests")
    create_job(session, run_id=run.id, stage="execute_tests")
    create_job(session, run_id=run.id, stage="analyze")

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


@app.get("/runs/{run_id}/execution-summary", response_model=ExecutionSummaryOut)
def get_execution_summary_endpoint(
    run_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> ExecutionSummaryOut:
    workspace = require_workspace(session, current_user)
    summary = ExecutionResultsService(session, workspace.id).get_execution_summary(run_id)
    return ExecutionSummaryOut.model_validate(summary)


@app.get("/runs/{run_id}/execution-log", response_model=ExecutionLogOut)
def get_execution_log_endpoint(
    run_id: str,
    suite: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> ExecutionLogOut:
    workspace = require_workspace(session, current_user)
    payload = ExecutionResultsService(session, workspace.id).get_execution_log(run_id, suite)
    return ExecutionLogOut.model_validate(payload)


@app.get("/runs/{run_id}/analysis-summary", response_model=AnalysisSummaryOut)
def get_analysis_summary_endpoint(
    run_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> AnalysisSummaryOut:
    workspace = require_workspace(session, current_user)
    summary = AnalysisResultsService(session, workspace.id).get_analysis_summary(run_id)
    return AnalysisSummaryOut.model_validate(summary)


@app.get("/runs/{run_id}/analysis-report", response_model=AnalysisReportOut)
def get_analysis_report_endpoint(
    run_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> AnalysisReportOut:
    workspace = require_workspace(session, current_user)
    payload = AnalysisResultsService(session, workspace.id).get_analysis_report(run_id)
    return AnalysisReportOut.model_validate(payload)


@app.get("/runs/{run_id}/generated-tests/manifest", response_model=GeneratedTestManifestOut)
def get_generated_tests_manifest_endpoint(
    run_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> GeneratedTestManifestOut:
    workspace = require_workspace(session, current_user)
    manifest = GeneratedTestsService(session, workspace.id).get_generated_test_manifest(run_id)
    return GeneratedTestManifestOut.model_validate(manifest.model_dump())


@app.get("/runs/{run_id}/generated-tests/tree", response_model=GeneratedTestTreeResponse, response_model_exclude_none=True)
def get_generated_tests_tree_endpoint(
    run_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> GeneratedTestTreeResponse:
    workspace = require_workspace(session, current_user)
    tree = GeneratedTestsService(session, workspace.id).get_generated_test_tree(run_id)
    return GeneratedTestTreeResponse.model_validate(tree)


@app.get("/runs/{run_id}/generated-tests/file", response_model=GeneratedTestFileContentResponse)
def get_generated_test_content_endpoint(
    run_id: str,
    path: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> GeneratedTestFileContentResponse:
    workspace = require_workspace(session, current_user)
    payload = GeneratedTestsService(session, workspace.id).get_generated_test_file_content(run_id, path)
    return GeneratedTestFileContentResponse.model_validate(payload.model_dump())


@app.get("/runs/{run_id}/generated-tests/cases", response_model=GeneratedTestCasesResponse)
def get_generated_test_cases_endpoint(
    run_id: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> GeneratedTestCasesResponse:
    workspace = require_workspace(session, current_user)
    payload = GeneratedTestsService(session, workspace.id).get_generated_test_cases(run_id)
    return GeneratedTestCasesResponse.model_validate(payload)


@app.get("/runs/{run_id}/generated-tests/content", response_model=GeneratedTestFileContentResponse, include_in_schema=False)
def get_generated_test_content_legacy_endpoint(
    run_id: str,
    path: str,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> GeneratedTestFileContentResponse:
    return get_generated_test_content_endpoint(run_id, path, session, current_user)
