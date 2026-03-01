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

export type ProjectPayload = {
  name: string;
  repo_url: string;
  default_branch: string;
};
