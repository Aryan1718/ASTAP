import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from shared.repository import get_job_by_stage, get_run
from shared.storage import download_storage_object_text


class AnalysisResultsService:
    def __init__(self, session: Session, workspace_id: str) -> None:
        self.session = session
        self.workspace_id = workspace_id

    def get_analysis_summary(self, run_id: str) -> dict:
        run = self._get_accessible_run(run_id)
        job = self._get_analyze_job(run.id)
        payload = self._load_summary_payload(job)
        artifacts = self._normalize_artifacts(job.artifacts_json)
        if payload is not None:
            return {
                "run_id": run.id,
                "stage_status": job.status,
                "heuristics_version": int(payload.get("heuristics_version", 1)),
                "overall_assessment": payload.get("overall_assessment", "mixed_results"),
                "baseline_repo_status": payload.get("baseline_repo_status", "unknown"),
                "generated_tests_status": payload.get("generated_tests_status", "unknown"),
                "infrastructure_status": payload.get("infrastructure_status", "unknown"),
                "analysis_mode": payload.get("analysis_mode", "deterministic_only"),
                "llm_summary_available": bool(payload.get("llm_summary_available", False)),
                "counts": payload.get("counts", {}),
                "highlights": payload.get("highlights", []),
                "trend": payload.get("trend", {"status": "unavailable", "counts": {}, "new_findings": [], "fixed_findings": []}),
                "artifacts": artifacts,
            }

        output_json = job.output_json if isinstance(job.output_json, dict) else {}
        if not output_json and not artifacts:
            raise HTTPException(status_code=404, detail="Analysis results not available")
        return {
            "run_id": run.id,
            "stage_status": job.status,
            "heuristics_version": int(output_json.get("heuristics_version", 1)),
            "overall_assessment": output_json.get("overall_assessment", "mixed_results"),
            "baseline_repo_status": output_json.get("baseline_repo_status", "unknown"),
            "generated_tests_status": output_json.get("generated_tests_status", "unknown"),
            "infrastructure_status": output_json.get("infrastructure_status", "unknown"),
            "analysis_mode": output_json.get("analysis_mode", "deterministic_only"),
            "llm_summary_available": bool(output_json.get("llm_summary_available", False)),
            "counts": output_json.get("counts", {}),
            "highlights": output_json.get("highlights", []),
            "trend": output_json.get("trend", {"status": "unavailable", "counts": {}, "new_findings": [], "fixed_findings": []}),
            "artifacts": artifacts,
        }

    def get_analysis_report(self, run_id: str) -> dict:
        run = self._get_accessible_run(run_id)
        job = self._get_analyze_job(run.id)
        artifact = next(
            (item for item in job.artifacts_json if item.get("artifact_type") == "analysis_report"),
            None,
        )
        if artifact is None:
            raise HTTPException(status_code=404, detail="Analysis report not found")
        try:
            content = download_storage_object_text(artifact["bucket"], artifact["key"])
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, FileNotFoundError):
                raise HTTPException(status_code=404, detail="Analysis report not found") from exc
            raise HTTPException(status_code=500, detail="Failed to read analysis report") from exc
        return {
            "run_id": run.id,
            "path": artifact["path"],
            "content": content,
        }

    def _get_accessible_run(self, run_id: str):
        run = get_run(self.session, run_id, self.workspace_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    def _get_analyze_job(self, run_id: str):
        job = get_job_by_stage(self.session, run_id, "analyze")
        if job is None or job.status in {"pending", "running", "retrying"}:
            raise HTTPException(status_code=404, detail="Analysis results not available")
        return job

    def _load_summary_payload(self, job) -> dict | None:
        artifact = next(
            (item for item in job.artifacts_json if item.get("artifact_type") == "analysis_summary"),
            None,
        )
        if artifact is None:
            return None
        try:
            return json.loads(download_storage_object_text(artifact["bucket"], artifact["key"]))
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, FileNotFoundError):
                return None
            raise HTTPException(status_code=500, detail="Failed to read analysis results") from exc

    def _normalize_artifacts(self, artifacts_json: list[dict] | None) -> list[dict]:
        artifacts: list[dict] = []
        for artifact in artifacts_json or []:
            artifact_type = artifact.get("artifact_type")
            bucket = artifact.get("bucket")
            key = artifact.get("key")
            path = artifact.get("path")
            if not all(isinstance(value, str) for value in [artifact_type, bucket, key, path]):
                continue
            artifacts.append(
                {
                    "artifact_type": artifact_type,
                    "bucket": bucket,
                    "key": key,
                    "path": path,
                }
            )
        return artifacts
