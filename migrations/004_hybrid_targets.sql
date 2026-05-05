alter table targets
add column if not exists target_key text;

update targets
set target_key = md5(
  coalesce(target_type, '') || '|' ||
  coalesce(file_path, '') || '|' ||
  coalesce(symbol, '') || '|' ||
  coalesce(signature, '')
)
where target_key is null or target_key = '';

alter table targets
alter column target_key set not null;

create unique index if not exists targets_run_id_target_key_uidx
on targets (run_id, target_key);

create index if not exists targets_run_id_file_path_idx
on targets (run_id, file_path);
