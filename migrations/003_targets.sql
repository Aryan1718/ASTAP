create table if not exists targets (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references runs(id) on delete cascade,
  target_type text not null,
  file_path text not null,
  symbol text not null,
  signature text null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz default now()
);

create index if not exists targets_run_id_idx on targets (run_id);
create index if not exists targets_target_type_idx on targets (target_type);

alter table targets enable row level security;

drop policy if exists "targets_select_own_workspace" on targets;
create policy "targets_select_own_workspace"
on targets
for select
using (
  exists (
    select 1
    from runs
    join workspaces on workspaces.id = runs.workspace_id
    where runs.id = targets.run_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "targets_insert_own_workspace" on targets;
create policy "targets_insert_own_workspace"
on targets
for insert
with check (
  exists (
    select 1
    from runs
    join workspaces on workspaces.id = runs.workspace_id
    where runs.id = targets.run_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "targets_update_own_workspace" on targets;
create policy "targets_update_own_workspace"
on targets
for update
using (
  exists (
    select 1
    from runs
    join workspaces on workspaces.id = runs.workspace_id
    where runs.id = targets.run_id
      and workspaces.owner_user_id = auth.uid()
  )
)
with check (
  exists (
    select 1
    from runs
    join workspaces on workspaces.id = runs.workspace_id
    where runs.id = targets.run_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "targets_delete_own_workspace" on targets;
create policy "targets_delete_own_workspace"
on targets
for delete
using (
  exists (
    select 1
    from runs
    join workspaces on workspaces.id = runs.workspace_id
    where runs.id = targets.run_id
      and workspaces.owner_user_id = auth.uid()
  )
);
