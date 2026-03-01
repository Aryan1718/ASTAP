import subprocess
import tempfile
from pathlib import Path
from shutil import rmtree

from shared.config import settings
from shared.db import SessionLocal
from shared.queue import get_queue
from shared.repository import (
    claim_job,
    get_job_by_stage,
    get_run,
    mark_job_failed,
    mark_job_succeeded_with_artifacts,
    mark_run_failed,
    mark_run_running,
    set_job_rq_id,
    update_run_snapshot,
)
from worker.app.jobs.common import file_sha256, upload_file_to_storage


def run_command(args: list[str], cwd: str | None = None) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def ingest_job(run_id: str, job_id: str) -> None:
    session = SessionLocal()
    temp_dir = Path(tempfile.mkdtemp(prefix="ingest-"))
    try:
        job = claim_job(session, job_id)
        if job is None:
            return

        run = get_run(session, run_id)
        if run is None:
            raise RuntimeError("Run not found")

        mark_run_running(session, run_id)

        repo_path = temp_dir / "repo"
        run_command(["git", "clone", run.project.repo_url, str(repo_path)])
        run_command(["git", "checkout", run.ref_requested], cwd=str(repo_path))
        ref_resolved = run_command(["git", "rev-parse", "HEAD"], cwd=str(repo_path))

        snapshot_path = temp_dir / "snapshot.tar.gz"
        subprocess.run(
            ["git", "archive", "--format=tar.gz", "-o", str(snapshot_path), ref_resolved],
            cwd=repo_path,
            check=True,
        )

        object_key = f"{run.workspace_id}/{run.project_id}/{run.id}/snapshot/snapshot.tar.gz"
        upload_file_to_storage(
            bucket=settings.supabase_storage_bucket,
            object_key=object_key,
            source=snapshot_path,
            content_type="application/gzip",
        )

        update_run_snapshot(
            session,
            run_id=run.id,
            ref_resolved=ref_resolved,
            bucket=settings.supabase_storage_bucket,
            key=object_key,
            sha256=file_sha256(snapshot_path),
            size_bytes=snapshot_path.stat().st_size,
        )

        snapshot_artifact = {
            "artifact_type": "snapshot",
            "bucket": settings.supabase_storage_bucket,
            "key": object_key,
        }
        mark_job_succeeded_with_artifacts(
            session,
            job_id=job.id,
            output_json={"ref_resolved": ref_resolved, "snapshot_key": object_key},
            artifacts_json=[snapshot_artifact],
        )

        discover = get_job_by_stage(session, run.id, "discover")
        if discover is None:
            raise RuntimeError("Discover job not found")

        rq_job = get_queue("discover").enqueue("worker.app.jobs.discover_job", run.id, discover.id)
        set_job_rq_id(session, discover.id, rq_job.id)
    except Exception as exc:  # noqa: BLE001
        mark_job_failed(session, job_id, f"{type(exc).__name__}: {exc}")
        mark_run_failed(session, run_id)
        raise
    finally:
        session.close()
        rmtree(temp_dir, ignore_errors=True)
