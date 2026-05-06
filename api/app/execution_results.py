import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from shared.repository import get_job_by_stage, get_run
from shared.storage import download_storage_object_text


class ExecutionResultsService:
    def __init__(self, session: Session, workspace_id: str) -> None:
        self.session = session
        self.workspace_id = workspace_id

    def get_execution_summary(self, run_id: str) -> dict:
        run = self._get_accessible_run(run_id)
        job = self._get_execute_tests_job(run.id)

        results_payload = self._load_results_payload(job)
        artifacts = self._normalize_artifacts(job.artifacts_json)
        if results_payload is not None:
            return {
                "run_id": run.id,
                "stage_status": job.status,
                "framework": results_payload.get("framework", "pytest"),
                "overall_result": results_payload.get("overall_result"),
                "environment": results_payload.get("environment"),
                "isolation": results_payload.get("isolation"),
                "install": results_payload.get("install"),
                "execution_plan": results_payload.get("execution_plan"),
                "attempted_commands": results_payload.get("attempted_commands", []),
                "existing_tests": results_payload.get("existing_tests"),
                "generated_tests": results_payload.get("generated_tests"),
                "combined_tests": results_payload.get("combined_tests"),
                "artifacts": artifacts,
            }

        output_json = job.output_json if isinstance(job.output_json, dict) else {}
        if not output_json and not artifacts:
            raise HTTPException(status_code=404, detail="Execution results not available")

        return {
            "run_id": run.id,
            "stage_status": job.status,
                "framework": output_json.get("framework", "pytest"),
                "overall_result": output_json.get("overall_result"),
                "environment": output_json.get("environment") or {"python_version": output_json.get("python_version")},
                "isolation": output_json.get("isolation"),
                "install": output_json.get("install"),
                "execution_plan": output_json.get("execution_plan"),
                "attempted_commands": output_json.get("attempted_commands", []),
                "existing_tests": output_json.get("existing_tests"),
                "generated_tests": output_json.get("generated_tests"),
            "combined_tests": output_json.get("combined_tests"),
            "artifacts": artifacts,
        }

    def get_execution_log(self, run_id: str, suite_key: str) -> dict:
        normalized_suite = _normalize_suite_key(suite_key)
        run = self._get_accessible_run(run_id)
        job = self._get_execute_tests_job(run.id)
        artifact = self._resolve_log_artifact(job, normalized_suite)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Execution log not found")

        bucket = artifact.get("bucket")
        key = artifact.get("key")
        path = artifact.get("path")
        if not isinstance(bucket, str) or not isinstance(key, str) or not isinstance(path, str):
            raise HTTPException(status_code=500, detail="Execution log metadata is invalid")

        try:
            content = download_storage_object_text(bucket, key)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, FileNotFoundError):
                raise HTTPException(status_code=404, detail="Execution log not found") from exc
            raise HTTPException(status_code=500, detail="Failed to read execution log") from exc

        return {
            "run_id": run.id,
            "suite_key": normalized_suite,
            "path": path,
            "content": content,
        }

    def _get_accessible_run(self, run_id: str):
        run = get_run(self.session, run_id, self.workspace_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    def _get_execute_tests_job(self, run_id: str):
        job = get_job_by_stage(self.session, run_id, "execute_tests")
        if job is None or job.status in {"pending", "running", "retrying"}:
            raise HTTPException(status_code=404, detail="Execution results not available")
        return job

    def _load_results_payload(self, job) -> dict | None:
        artifact = next(
            (
                candidate
                for candidate in job.artifacts_json
                if candidate.get("artifact_type") == "execution_results"
            ),
            None,
        )
        if artifact is None:
            return None

        bucket = artifact.get("bucket")
        key = artifact.get("key")
        if not isinstance(bucket, str) or not isinstance(key, str):
            raise HTTPException(status_code=500, detail="Execution results metadata is invalid")

        try:
            payload = download_storage_object_text(bucket, key)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, FileNotFoundError):
                return None
            raise HTTPException(status_code=500, detail="Failed to read execution results") from exc

        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail="Execution results payload is invalid") from exc

    def _resolve_log_artifact(self, job, suite_key: str) -> dict | None:
        expected_path = f"execute_tests/logs/{suite_key}-tests.log"
        return next(
            (
                artifact
                for artifact in job.artifacts_json
                if artifact.get("artifact_type") == "execution_log" and artifact.get("path") == expected_path
            ),
            None,
        )

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


def _normalize_suite_key(value: str) -> str:
    suite_key = value.strip().lower()
    if suite_key not in {"existing", "generated", "combined"}:
        raise HTTPException(status_code=400, detail="Unsupported suite key")
    return suite_key
