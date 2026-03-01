create extension if not exists pgcrypto;

create unique index if not exists workspaces_owner_user_id_key on workspaces (owner_user_id);
create index if not exists projects_workspace_id_idx on projects (workspace_id);
create index if not exists runs_workspace_id_idx on runs (workspace_id);
create index if not exists jobs_run_id_idx on jobs (run_id);

insert into storage.buckets (id, name, public)
values ('runs', 'runs', false)
on conflict (id) do update
set
  name = excluded.name,
  public = excluded.public;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.workspaces (id, owner_user_id, name)
  values (
    gen_random_uuid(),
    new.id,
    coalesce(
      nullif(new.raw_user_meta_data ->> 'workspace_name', ''),
      concat(split_part(coalesce(new.email, 'workspace'), '@', 1), '''s Workspace')
    )
  )
  on conflict (owner_user_id) do nothing;

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;

create trigger on_auth_user_created
after insert on auth.users
for each row execute procedure public.handle_new_user();

insert into public.workspaces (id, owner_user_id, name)
select
  gen_random_uuid(),
  users.id,
  coalesce(
    nullif(users.raw_user_meta_data ->> 'workspace_name', ''),
    concat(split_part(coalesce(users.email, 'workspace'), '@', 1), '''s Workspace')
  )
from auth.users as users
on conflict (owner_user_id) do nothing;

alter table workspaces enable row level security;
alter table projects enable row level security;
alter table runs enable row level security;
alter table jobs enable row level security;

drop policy if exists "workspaces_select_own" on workspaces;
create policy "workspaces_select_own"
on workspaces
for select
using (owner_user_id = auth.uid());

drop policy if exists "workspaces_insert_own" on workspaces;
create policy "workspaces_insert_own"
on workspaces
for insert
with check (owner_user_id = auth.uid());

drop policy if exists "workspaces_update_own" on workspaces;
create policy "workspaces_update_own"
on workspaces
for update
using (owner_user_id = auth.uid())
with check (owner_user_id = auth.uid());

drop policy if exists "workspaces_delete_own" on workspaces;
create policy "workspaces_delete_own"
on workspaces
for delete
using (owner_user_id = auth.uid());

drop policy if exists "projects_select_own_workspace" on projects;
create policy "projects_select_own_workspace"
on projects
for select
using (
  exists (
    select 1
    from workspaces
    where workspaces.id = projects.workspace_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "projects_insert_own_workspace" on projects;
create policy "projects_insert_own_workspace"
on projects
for insert
with check (
  exists (
    select 1
    from workspaces
    where workspaces.id = projects.workspace_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "projects_update_own_workspace" on projects;
create policy "projects_update_own_workspace"
on projects
for update
using (
  exists (
    select 1
    from workspaces
    where workspaces.id = projects.workspace_id
      and workspaces.owner_user_id = auth.uid()
  )
)
with check (
  exists (
    select 1
    from workspaces
    where workspaces.id = projects.workspace_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "projects_delete_own_workspace" on projects;
create policy "projects_delete_own_workspace"
on projects
for delete
using (
  exists (
    select 1
    from workspaces
    where workspaces.id = projects.workspace_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "runs_select_own_workspace" on runs;
create policy "runs_select_own_workspace"
on runs
for select
using (
  exists (
    select 1
    from workspaces
    where workspaces.id = runs.workspace_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "runs_insert_own_workspace" on runs;
create policy "runs_insert_own_workspace"
on runs
for insert
with check (
  exists (
    select 1
    from workspaces
    where workspaces.id = runs.workspace_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "runs_update_own_workspace" on runs;
create policy "runs_update_own_workspace"
on runs
for update
using (
  exists (
    select 1
    from workspaces
    where workspaces.id = runs.workspace_id
      and workspaces.owner_user_id = auth.uid()
  )
)
with check (
  exists (
    select 1
    from workspaces
    where workspaces.id = runs.workspace_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "runs_delete_own_workspace" on runs;
create policy "runs_delete_own_workspace"
on runs
for delete
using (
  exists (
    select 1
    from workspaces
    where workspaces.id = runs.workspace_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "jobs_select_own_workspace" on jobs;
create policy "jobs_select_own_workspace"
on jobs
for select
using (
  exists (
    select 1
    from runs
    join workspaces on workspaces.id = runs.workspace_id
    where runs.id = jobs.run_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "jobs_insert_own_workspace" on jobs;
create policy "jobs_insert_own_workspace"
on jobs
for insert
with check (
  exists (
    select 1
    from runs
    join workspaces on workspaces.id = runs.workspace_id
    where runs.id = jobs.run_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "jobs_update_own_workspace" on jobs;
create policy "jobs_update_own_workspace"
on jobs
for update
using (
  exists (
    select 1
    from runs
    join workspaces on workspaces.id = runs.workspace_id
    where runs.id = jobs.run_id
      and workspaces.owner_user_id = auth.uid()
  )
)
with check (
  exists (
    select 1
    from runs
    join workspaces on workspaces.id = runs.workspace_id
    where runs.id = jobs.run_id
      and workspaces.owner_user_id = auth.uid()
  )
);

drop policy if exists "jobs_delete_own_workspace" on jobs;
create policy "jobs_delete_own_workspace"
on jobs
for delete
using (
  exists (
    select 1
    from runs
    join workspaces on workspaces.id = runs.workspace_id
    where runs.id = jobs.run_id
      and workspaces.owner_user_id = auth.uid()
  )
);
