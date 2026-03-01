create extension if not exists pgcrypto;

create table if not exists workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  owner_user_id uuid not null,
  created_at timestamptz default now()
);

create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  name text not null,
  repo_url text not null,
  default_branch text not null default 'main',
  language text null,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  project_id uuid not null references projects(id) on delete cascade,
  status text not null check (status in ('queued','running','succeeded','failed','canceled')),
  ref_requested text not null,
  ref_resolved text null,
  snapshot_bucket text null,
  snapshot_key text null,
  snapshot_sha256 text null,
  snapshot_size_bytes bigint null,
  run_config jsonb default '{}'::jsonb,
  summary jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  started_at timestamptz null,
  finished_at timestamptz null,
  updated_at timestamptz default now()
);

create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references runs(id) on delete cascade,
  stage text not null check (stage in ('ingest','discover','generate_tests','execute_tests','analyze')),
  status text not null check (status in ('pending','running','succeeded','failed','retrying','canceled')),
  rq_job_id text null,
  attempt int default 0,
  max_attempts int default 3,
  locked_by text null,
  locked_at timestamptz null,
  started_at timestamptz null,
  finished_at timestamptz null,
  error_message text null,
  input_json jsonb default '{}'::jsonb,
  output_json jsonb default '{}'::jsonb,
  artifacts_json jsonb default '[]'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (run_id, stage)
);
