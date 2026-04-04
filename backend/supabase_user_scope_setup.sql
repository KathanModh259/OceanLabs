-- PostgreSQL migration for Supabase.
-- Run this in Supabase SQL Editor (PostgreSQL).
-- Purpose: enforce per-user isolation for meetings and transcripts.

begin;

-- 1) Ensure ownership columns exist.
alter table if exists public.meetings
  add column if not exists user_id uuid references auth.users(id) on delete cascade;

alter table if exists public.transcripts
  add column if not exists user_id uuid references auth.users(id) on delete cascade;

-- 2) Helpful indexes for user-scoped queries.
create index if not exists idx_meetings_user_id_created_at
  on public.meetings (user_id, created_at desc);

create index if not exists idx_transcripts_meeting_id
  on public.transcripts (meeting_id);

create index if not exists idx_transcripts_user_id
  on public.transcripts (user_id);

-- 3) Backfill transcript ownership from parent meeting where possible.
update public.transcripts t
set user_id = m.user_id
from public.meetings m
where t.meeting_id = m.id
  and t.user_id is null
  and m.user_id is not null;

-- 4) Keep transcripts.user_id synced from meetings.user_id.
create or replace function public.sync_transcript_user_id_from_meeting()
returns trigger
language plpgsql
as $$
begin
  if new.user_id is null and new.meeting_id is not null then
    select m.user_id
    into new.user_id
    from public.meetings m
    where m.id = new.meeting_id;
  end if;

  return new;
end;
$$;

drop trigger if exists trg_sync_transcript_user_id on public.transcripts;

create trigger trg_sync_transcript_user_id
before insert or update on public.transcripts
for each row
execute function public.sync_transcript_user_id_from_meeting();

-- 5) RLS enablement.
alter table if exists public.meetings enable row level security;
alter table if exists public.transcripts enable row level security;

-- 6) Recreate policies idempotently.
drop policy if exists meetings_select_own on public.meetings;
drop policy if exists meetings_insert_own on public.meetings;
drop policy if exists meetings_update_own on public.meetings;
drop policy if exists meetings_delete_own on public.meetings;

drop policy if exists transcripts_select_own on public.transcripts;
drop policy if exists transcripts_insert_own on public.transcripts;
drop policy if exists transcripts_update_own on public.transcripts;
drop policy if exists transcripts_delete_own on public.transcripts;

create policy meetings_select_own
on public.meetings
for select
using (auth.uid() = user_id);

create policy meetings_insert_own
on public.meetings
for insert
with check (auth.uid() = user_id);

create policy meetings_update_own
on public.meetings
for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy meetings_delete_own
on public.meetings
for delete
using (auth.uid() = user_id);

create policy transcripts_select_own
on public.transcripts
for select
using (
  exists (
    select 1
    from public.meetings m
    where m.id = transcripts.meeting_id
      and m.user_id = auth.uid()
  )
);

create policy transcripts_insert_own
on public.transcripts
for insert
with check (
  exists (
    select 1
    from public.meetings m
    where m.id = transcripts.meeting_id
      and m.user_id = auth.uid()
  )
);

create policy transcripts_update_own
on public.transcripts
for update
using (
  exists (
    select 1
    from public.meetings m
    where m.id = transcripts.meeting_id
      and m.user_id = auth.uid()
  )
)
with check (
  exists (
    select 1
    from public.meetings m
    where m.id = transcripts.meeting_id
      and m.user_id = auth.uid()
  )
);

create policy transcripts_delete_own
on public.transcripts
for delete
using (
  exists (
    select 1
    from public.meetings m
    where m.id = transcripts.meeting_id
      and m.user_id = auth.uid()
  )
);

commit;

-- Optional one-time backfill for legacy meetings (replace with a valid user UUID):
-- update public.meetings
-- set user_id = '00000000-0000-0000-0000-000000000000'::uuid
-- where user_id is null;
