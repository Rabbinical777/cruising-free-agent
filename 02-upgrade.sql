-- Run BEFORE deploying the updated checker. Existing discoveries are preserved.
begin;
create table if not exists public.bursary_page_checks (
 url text primary key references public.bursary_discoveries(url),
 content_hash text not null,
 last_checked_at timestamptz not null default now(),
 last_changed_at timestamptz not null default now(),
 deadline_evidence jsonb not null default '[]',
 requirement_evidence jsonb not null default '[]'
);
alter table public.bursary_page_checks enable row level security;
revoke all on public.bursary_page_checks from public, anon, authenticated;
create or replace function public.record_bursary_page_check(
 p_url text, p_hash text, p_deadlines jsonb, p_requirements jsonb
) returns jsonb language plpgsql security definer set search_path='' as $$
declare old_hash text; is_changed boolean;
begin
 if p_hash !~ '^[0-9a-f]{64}$' or jsonb_typeof(p_deadlines) <> 'array'
 or jsonb_typeof(p_requirements) <> 'array' then
 raise exception 'Invalid observation'; end if;
 -- Serialize observations for this discovery; preserve all review decisions.
 perform 1 from public.bursary_discoveries where url=p_url for update;
 if not found then raise exception 'Unknown discovery'; end if;
 select content_hash into old_hash from public.bursary_page_checks where url=p_url;
 is_changed := old_hash is not null and old_hash <> p_hash;
 insert into public.bursary_page_checks(url,content_hash,deadline_evidence,requirement_evidence)
 values(p_url,p_hash,p_deadlines,p_requirements)
 on conflict(url) do update set
 content_hash=excluded.content_hash,last_checked_at=now(),
 last_changed_at=case when public.bursary_page_checks.content_hash <> excluded.content_hash
 then now() else public.bursary_page_checks.last_changed_at end,
 deadline_evidence=excluded.deadline_evidence,requirement_evidence=excluded.requirement_evidence;
 return jsonb_build_object('changed',is_changed,'first_check',old_hash is null);
end $$;
revoke all on function public.record_bursary_page_check(text,text,jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.record_bursary_page_check(text,text,jsonb,jsonb) to service_role;
commit;
