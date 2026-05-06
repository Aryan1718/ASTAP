export type Project = {
  id: string;
  name: string;
  repo_url: string;
  default_branch: string;
  created_at: string;
};

export type RunStart = {
  run_id: string;
  project_id: string;
  status: string;
  ref_requested: string;
  created_at: string;
};

export type RunListItem = {
  id: string;
  project_id: string;
  project_name: string;
  status: string;
  ref_requested: string;
  ref_resolved?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  progress_percent: number;
};

export type Stage = {
  stage: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  error_message?: string | null;
};

export type Snapshot = {
  bucket: string;
  key: string;
  size_bytes?: number | null;
  sha256?: string | null;
};

export type ExecutionArtifact = {
  artifact_type: string;
  bucket: string;
  key: string;
  path: string;
};

export type ExecutionEnvironment = {
  python_version?: string | null;
  execution_image?: string | null;
  working_directory?: string | null;
  generated_tests_root?: string | null;
};

export type ExecutionSuite = {
  suite_key: string;
  status: string;
  command?: string[] | null;
  exit_code?: number | null;
  collected: number;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  duration_seconds: number;
  log_path?: string | null;
  junit_path?: string | null;
};

export type ExecutionSummary = {
  run_id: string;
  stage_status: string;
  framework: string;
  overall_result?: string | null;
  environment?: ExecutionEnvironment | null;
  existing_tests?: ExecutionSuite | null;
  generated_tests?: ExecutionSuite | null;
  combined_tests?: ExecutionSuite | null;
  artifacts: ExecutionArtifact[];
};

export type ExecutionLog = {
  run_id: string;
  suite_key: string;
  path: string;
  content: string;
};

export type AnalysisArtifact = {
  artifact_type: string;
  bucket: string;
  key: string;
  path: string;
};

export type AnalysisCount = {
  existing_failed: number;
  generated_failed: number;
  high_signal_failures: number;
  infrastructure_errors: number;
  low_signal_failures: number;
  unrunnable_failures: number;
  flaky_suspects: number;
};

export type AnalysisHighlight = {
  kind: string;
  priority: string;
  headline: string;
  severity: string;
  confidence: string;
  confidence_score: number;
  failure_category: string;
  suite?: string | null;
  test_name?: string | null;
  target_key?: string | null;
  symbol?: string | null;
  source_file?: string | null;
  recipe_id?: string | null;
  recipe_name?: string | null;
  generated_test_file?: string | null;
  risk_tags: string[];
  heuristic_tags: string[];
  evidence: string[];
};

export type AnalysisSummary = {
  run_id: string;
  stage_status: string;
  heuristics_version: number;
  overall_assessment: string;
  baseline_repo_status: string;
  generated_tests_status: string;
  infrastructure_status: string;
  analysis_mode: string;
  llm_summary_available: boolean;
  counts: AnalysisCount;
  highlights: AnalysisHighlight[];
  artifacts: AnalysisArtifact[];
};

export type AnalysisReport = {
  run_id: string;
  path: string;
  content: string;
};

export type RunDetail = {
  id: string;
  project_id: string;
  status: string;
  ref_requested: string;
  ref_resolved?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  stages: Stage[];
  progress_percent: number;
  snapshot?: Snapshot | null;
};

export type GeneratedTestManifestEntry = {
  target_key: string;
  target_type: string;
  symbol: string;
  source_file: string;
  generated_test_file?: string | null;
  test_kind?: string | null;
  status: string;
  skip_reason?: string | null;
};

export type GeneratedTestManifest = {
  version: number;
  run_id: string;
  generated_at: string;
  files: GeneratedTestManifestEntry[];
};

export type GeneratedTestFileContent = {
  run_id?: string;
  path: string;
  content: string;
  language: string;
};

export type ProjectPayload = {
  name: string;
  repo_url: string;
  default_branch: string;
};
