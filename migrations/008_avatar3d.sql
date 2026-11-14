-- 3D avatar (the editor's choices) per account, plus an unfinished draft so the editor can pick up where it was left.
alter table users add column if not exists avatar3d jsonb;
alter table users add column if not exists avatar3d_draft jsonb;
alter table users add column if not exists avatar3d_updated_at timestamptz;
