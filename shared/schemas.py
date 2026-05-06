from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl

from shared.targets import GeneratedTestManifestEntry


class ProjectCreate(BaseModel):
    name: str
    repo_url: HttpUrl
    default_branch: str = "main"


class ProjectOut(BaseModel):
    id: str
    name: str
    repo_url: str
    default_branch: str
    created_at: datetime


class RunCreate(BaseModel):
    ref: Optional[str] = None


class RunStartOut(BaseModel):
    run_id: str
    project_id: str
    status: str
    ref_requested: str
    created_at: datetime


class RunListItemOut(BaseModel):
    id: str
    project_id: str
    project_name: str
    status: str
    ref_requested: str
    ref_resolved: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    progress_percent: int


class StageOut(BaseModel):
    stage: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None


class SnapshotOut(BaseModel):
    bucket: str
    key: str
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None


class RunDetailOut(BaseModel):
    id: str
    project_id: str
    status: str
    ref_requested: str
    ref_resolved: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    stages: list[StageOut]
    progress_percent: int
    snapshot: Optional[SnapshotOut] = None


class RunSummaryOut(BaseModel):
    overall_assessment: Optional[str] = None
    headline: Optional[str] = None
    baseline_repo_status: Optional[str] = None
    generated_tests_status: Optional[str] = None
    infrastructure_status: Optional[str] = None
    high_signal_failures_count: int = 0
    llm_summary_available: bool = False


class ExecutionArtifactOut(BaseModel):
    artifact_type: str
    bucket: str
    key: str
    path: str


class ExecutionEnvironmentOut(BaseModel):
    python_version: Optional[str] = None
    execution_image: Optional[str] = None
    working_directory: Optional[str] = None
    generated_tests_root: Optional[str] = None
    execution_mode: Optional[str] = None
    worker_has_docker_socket: Optional[bool] = None


class ExecutionIsolationOut(BaseModel):
    network_mode: Optional[str] = None
    read_only_rootfs: Optional[bool] = None
    repo_mount_read_only: Optional[bool] = None
    cap_drop_all: Optional[bool] = None
    no_new_privileges: Optional[bool] = None
    cpus: Optional[float] = None
    memory_mb: Optional[int] = None
    pids: Optional[int] = None
    tmpfs_mb: Optional[int] = None
    worker_has_docker_socket: Optional[bool] = None


class ExecutionInstallOut(BaseModel):
    offline: Optional[bool] = None
    steps: list[dict] = Field(default_factory=list)


class ExecutionCommandOut(BaseModel):
    command: list[str]
    source: Optional[str] = None


class ExecutionPlanOut(BaseModel):
    framework: str
    install_commands: list[ExecutionCommandOut] = Field(default_factory=list)
    existing_test_command: Optional[ExecutionCommandOut] = None
    generated_test_command: Optional[ExecutionCommandOut] = None
    suite_timeout_seconds: Optional[int] = None
    detection_notes: list[str] = Field(default_factory=list)


class ExecutionSuiteOut(BaseModel):
    suite_key: str
    status: str
    command: Optional[list[str]] = None
    command_source: Optional[str] = None
    exit_code: Optional[int] = None
    collected: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    log_path: Optional[str] = None
    junit_path: Optional[str] = None


class ExecutionSummaryOut(BaseModel):
    run_id: str
    stage_status: str
    framework: str
    overall_result: Optional[str] = None
    environment: Optional[ExecutionEnvironmentOut] = None
    isolation: Optional[ExecutionIsolationOut] = None
    install: Optional[ExecutionInstallOut | list[dict]] = None
    execution_plan: Optional[ExecutionPlanOut] = None
    attempted_commands: list[list[str]] = Field(default_factory=list)
    existing_tests: Optional[ExecutionSuiteOut] = None
    generated_tests: Optional[ExecutionSuiteOut] = None
    combined_tests: Optional[ExecutionSuiteOut] = None
    artifacts: list[ExecutionArtifactOut]


class ExecutionLogOut(BaseModel):
    run_id: str
    suite_key: str
    path: str
    content: str


class GeneratedTestManifestOut(BaseModel):
    version: int
    run_id: str
    generated_at: str
    files: list[GeneratedTestManifestEntry]


class GeneratedTestTreeNode(BaseModel):
    path: str
    name: str
    type: str
    target_key: str | None = None
    target_type: str | None = None
    test_kind: str | None = None
    symbol: str | None = None


class GeneratedTestTreeResponse(BaseModel):
    run_id: str
    root: str
    nodes: list[GeneratedTestTreeNode]


class GeneratedTestFileContentResponse(BaseModel):
    run_id: str
    path: str
    content: str
    language: str


class AnalysisArtifactOut(BaseModel):
    artifact_type: str
    bucket: str
    key: str
    path: str


class AnalysisCountOut(BaseModel):
    existing_failed: int = 0
    generated_failed: int = 0
    high_signal_failures: int = 0
    infrastructure_errors: int = 0
    low_signal_failures: int = 0
    unrunnable_failures: int = 0
    flaky_suspects: int = 0


class AnalysisHighlightOut(BaseModel):
    kind: str
    priority: str
    headline: str
    severity: str = "medium"
    confidence: str = "medium"
    confidence_score: float = 0.0
    failure_category: str = "product_failure"
    suite: Optional[str] = None
    test_name: Optional[str] = None
    target_key: Optional[str] = None
    symbol: Optional[str] = None
    source_file: Optional[str] = None
    recipe_id: Optional[str] = None
    recipe_name: Optional[str] = None
    generated_test_file: Optional[str] = None
    risk_tags: list[str] = Field(default_factory=list)
    heuristic_tags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class AnalysisSummaryOut(BaseModel):
    run_id: str
    stage_status: str
    heuristics_version: int = 1
    overall_assessment: str
    baseline_repo_status: str
    generated_tests_status: str
    infrastructure_status: str
    analysis_mode: str
    llm_summary_available: bool = False
    counts: AnalysisCountOut
    highlights: list[AnalysisHighlightOut] = Field(default_factory=list)
    artifacts: list[AnalysisArtifactOut]


class AnalysisReportOut(BaseModel):
    run_id: str
    path: str
    content: str
