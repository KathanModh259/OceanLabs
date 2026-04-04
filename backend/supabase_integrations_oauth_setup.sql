-- PostgreSQL migration for per-user OAuth integration storage.
-- Run in Supabase SQL Editor (PostgreSQL).

begin;

create extension if not exists pgcrypto;

create table if not exists public.integration_connections (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    provider text not null check (provider in ('slack', 'jira', 'notion')),
    connected boolean not null default false,
    access_token text,
    refresh_token text,
    token_type text,
    scope text,
    expires_at timestamptz,
    external_account_id text,
    external_workspace text,
    config jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, provider)
);

create index if not exists idx_integration_connections_user_provider
    on public.integration_connections (user_id, provider);

create or replace function public.set_integration_connections_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_set_integration_connections_updated_at on public.integration_connections;

create trigger trg_set_integration_connections_updated_at
before update on public.integration_connections
for each row
execute function public.set_integration_connections_updated_at();

alter table public.integration_connections enable row level security;

drop policy if exists integration_connections_select_own on public.integration_connections;
drop policy if exists integration_connections_insert_own on public.integration_connections;
drop policy if exists integration_connections_update_own on public.integration_connections;
drop policy if exists integration_connections_delete_own on public.integration_connections;

create policy integration_connections_select_own
on public.integration_connections
for select
using (auth.uid() = user_id);

create policy integration_connections_insert_own
on public.integration_connections
for insert
with check (auth.uid() = user_id);

create policy integration_connections_update_own
on public.integration_connections
for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy integration_connections_delete_own
on public.integration_connections
for delete
using (auth.uid() = user_id);

commit;
