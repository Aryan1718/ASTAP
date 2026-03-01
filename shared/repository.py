from uuid import uuid4

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.orm import Session, joinedload

from shared.models import Job, Project, Run, Target, Workspace


def get_workspace_for_user(session: Session, user_id: str) -> Workspace | None:
    stmt: Select[tuple[Workspace]] = select(Workspace).where(Workspace.owner_user_id == user_id)
    return session.scalar(stmt)


def create_project(session: Session, workspace_id: str, name: str, repo_url: str, default_branch: str) -> Project:
    project = Project(
        id=str(uuid4()),
        workspace_id=workspace_id,
        name=name,
        repo_url=repo_url,
        default_branch=default_branch,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def list_projects(session: Session, workspace_id: str) -> list[Project]:
    stmt: Select[tuple[Project]] = (
        select(Project)
        .where(Project.workspace_id == workspace_id)
        .order_by(Project.created_at.desc())
    )
    return list(session.scalars(stmt).all())


def get_project(session: Session, project_id: str, workspace_id: str) -> Project | None:
    stmt: Select[tuple[Project]] = select(Project).where(Project.id == project_id, Project.workspace_id == workspace_id)
    return session.scalar(stmt)


def create_run(session: Session, project: Project, ref_requested: str) -> Run:
    run = Run(
        id=str(uuid4()),
        workspace_id=project.workspace_id,
        project_id=project.id,
        status="queued",
        ref_requested=ref_requested,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_run(session: Session, run_id: str, workspace_id: str | None = None) -> Run | None:
    stmt: Select[tuple[Run]] = select(Run).options(joinedload(Run.project)).where(Run.id == run_id)
    if workspace_id is not None:
        stmt = stmt.where(Run.workspace_id == workspace_id)
    return session.scalar(stmt)


def list_runs(session: Session, workspace_id: str) -> list[Run]:
    stmt: Select[tuple[Run]] = (
        select(Run)
        .options(joinedload(Run.project))
        .where(Run.workspace_id == workspace_id)
        .order_by(Run.created_at.desc())
    )
    return list(session.scalars(stmt).all())


def create_job(session: Session, run_id: str, stage: str, rq_job_id: str | None = None) -> Job:
    job = Job(
        id=str(uuid4()),
        run_id=run_id,
        stage=stage,
        status="pending",
        rq_job_id=rq_job_id,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def set_job_rq_id(session: Session, job_id: str, rq_job_id: str) -> None:
    session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(rq_job_id=rq_job_id, updated_at=func.now())
    )
    session.commit()


def list_jobs_for_run(session: Session, run_id: str) -> list[Job]:
    stmt: Select[tuple[Job]] = select(Job).where(Job.run_id == run_id).order_by(Job.created_at.asc())
    return list(session.scalars(stmt).all())


def list_jobs_for_runs(session: Session, run_ids: list[str]) -> list[Job]:
    if not run_ids:
        return []

    stmt: Select[tuple[Job]] = select(Job).where(Job.run_id.in_(run_ids)).order_by(Job.created_at.asc())
    return list(session.scalars(stmt).all())


def claim_job(session: Session, job_id: str, locked_by: str = "worker") -> Job | None:
    result = session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == "pending")
        .values(
            status="running",
            locked_at=func.now(),
            locked_by=locked_by,
            started_at=func.now(),
            updated_at=func.now(),
            attempt=Job.attempt + 1,
        )
        .returning(Job)
    )
    job = result.scalar_one_or_none()
    session.commit()
    return job


def mark_job_succeeded(session: Session, job_id: str, output_json: dict | None = None) -> None:
    mark_job_succeeded_with_artifacts(session, job_id, output_json=output_json, artifacts_json=None)


def mark_job_succeeded_with_artifacts(
    session: Session,
    job_id: str,
    output_json: dict | None = None,
    artifacts_json: list[dict] | None = None,
) -> None:
    session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(
            status="succeeded",
            finished_at=func.now(),
            updated_at=func.now(),
            output_json=output_json or {},
            artifacts_json=artifacts_json if artifacts_json is not None else [],
            error_message=None,
        )
    )
    session.commit()


def mark_job_failed(session: Session, job_id: str, error_message: str) -> None:
    session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(
            status="failed",
            finished_at=func.now(),
            updated_at=func.now(),
            error_message=error_message,
        )
    )
    session.commit()


def mark_run_running(session: Session, run_id: str) -> None:
    session.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(status="running", started_at=func.coalesce(Run.started_at, func.now()), updated_at=func.now())
    )
    session.commit()


def mark_run_succeeded(session: Session, run_id: str, ref_resolved: str | None = None) -> None:
    values = {
        "status": "succeeded",
        "finished_at": func.now(),
        "updated_at": func.now(),
    }
    if ref_resolved is not None:
        values["ref_resolved"] = ref_resolved
    session.execute(update(Run).where(Run.id == run_id).values(**values))
    session.commit()


def mark_run_failed(session: Session, run_id: str) -> None:
    session.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(status="failed", finished_at=func.now(), updated_at=func.now())
    )
    session.commit()


def update_run_snapshot(
    session: Session,
    run_id: str,
    ref_resolved: str,
    bucket: str,
    key: str,
    sha256: str,
    size_bytes: int,
) -> None:
    session.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(
            ref_resolved=ref_resolved,
            snapshot_bucket=bucket,
            snapshot_key=key,
            snapshot_sha256=sha256,
            snapshot_size_bytes=size_bytes,
            updated_at=func.now(),
        )
    )
    session.commit()


def get_job_by_stage(session: Session, run_id: str, stage: str) -> Job | None:
    stmt: Select[tuple[Job]] = select(Job).where(Job.run_id == run_id, Job.stage == stage)
    return session.scalar(stmt)


def replace_targets_for_run(session: Session, run_id: str, targets: list[dict]) -> None:
    session.execute(delete(Target).where(Target.run_id == run_id))
    if targets:
        session.add_all(
            [
                Target(
                    id=str(uuid4()),
                    run_id=run_id,
                    target_type=target["target_type"],
                    file_path=target["file_path"],
                    symbol=target["symbol"],
                    signature=target.get("signature"),
                    target_metadata=target.get("metadata", {}),
                )
                for target in targets
            ]
        )
    session.commit()
