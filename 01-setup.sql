-- Run once in your Supabase SQL Editor. Does not alter your existing app tables.
begin;
create table if not exists public.bursary_discoveries (
  id uuid primary key default gen_random_uuid(),
  url text not null unique check (length(url) <= 2000 and url like 'https://%'),
  title text not null check (length(title) <= 500),
  source_key text not null,
  source_url text not null,
  first_discovered_at timestamptz not null default now(),
  status text not null default 'pending_review' check (status in ('pending_review','reviewed','rejected')),
  review_notes text
);
create table if not exists public.bursary_free_runs (
  id uuid primary key default gen_random_uuid(),
  source_key text not null,
  checked_at timestamptz not null default now(),
  status text not null check (status in ('succeeded','warning','failed')),
  links_found integer not null default 0,
  inserted_count integer not null default 0,
  message text
);
alter table public.bursary_discoveries enable row level security;
alter table public.bursary_free_runs enable row level security;
revoke all on public.bursary_discoveries, public.bursary_free_runs from public, anon, authenticated;
grant select, insert on public.bursary_discoveries, public.bursary_free_runs to service_role;
commit;
