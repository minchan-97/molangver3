-- ============================================================
-- 10_organism_schema.sql — 디지털 유기체 영속화
-- SQL Editor에 붙여넣고 실행. 여러 번 실행해도 안전합니다.
--
-- 설계: 스칼라 상태(관심/전이/사이클)는 단일 JSONB 행 + version CAS.
--       관측은 행으로 쌓는다 → 쿼리 가능. pkl blob 통째 저장 금지.
-- ============================================================

-- ---------- 스칼라 상태 (낙관적 잠금) ----------
create table if not exists organism_state (
  id                int primary key default 1,
  cycle             int         not null default 0,
  born_at           timestamptz not null default now(),
  interests         jsonb       not null default '{}'::jsonb,
  visited           jsonb       not null default '{}'::jsonb,
  transition_counts jsonb       not null default '{}'::jsonb,
  last_topic        text        not null default '',
  last_hourly_at    timestamptz,
  last_nightly_at   timestamptz,
  version           int         not null default 1,
  updated_at        timestamptz not null default now(),
  constraint organism_state_singleton check (id = 1)
);

insert into organism_state (id) values (1) on conflict (id) do nothing;

-- ---------- 관측 (행으로 쌓는다) ----------
create table if not exists organism_observations (
  id           bigserial primary key,
  uid          text        not null,          -- state.uid(url+title)
  topic        text        not null,
  title        text,
  text         text,
  url          text,
  status       text        not null,
  score        real,
  source_trust real,
  transition_p real,
  novelty      real,
  run_id       text,
  seen_at      timestamptz not null default now(),

  constraint obs_status_ok check (status in ('candidate','quarantine','reject')),
  -- 구조적 강제: 관측은 절대 신념이 아니다. 봤다 ≠ 믿는다.
  -- learned_facts 로 가려면 molang_facts 에 별도 insert 되어야 하고,
  -- 그쪽 제약(no_self_promotion)이 source='search' 의 human 승격을 막는다.
  constraint obs_not_belief check (status <> 'believed')
);

create unique index if not exists organism_obs_uid on organism_observations(uid);
create index if not exists organism_obs_status on organism_observations(status, seen_at desc);
create index if not exists organism_obs_topic  on organism_observations(topic, seen_at desc);

-- 토폴로지 재구성에 쓰는 최근 관측
create or replace view organism_obs_recent as
select * from organism_observations
where status in ('candidate','quarantine')
order by seen_at desc
limit 1500;

-- ---------- SOM 스냅샷 ----------
create table if not exists organism_som (
  id         int primary key default 1,
  blob       bytea not null,
  n_items    int,
  occupied   int,
  mean_qe    real,
  version    int   not null default 1,
  updated_at timestamptz not null default now(),
  constraint organism_som_singleton check (id = 1)
);

-- ---------- 실행 기록 (중복 실행 탐지 + 실패 추적) ----------
create table if not exists organism_runs (
  id         bigserial primary key,
  run_id     text not null unique,
  mode       text not null,
  topic      text,
  query      text,
  found      int,
  ingested   int,
  candidate  int,
  quarantine int,
  rejected   int,
  som        jsonb,
  error      text,
  started_at timestamptz not null default now(),
  ended_at   timestamptz
);

create index if not exists organism_runs_recent on organism_runs(started_at desc);

-- ---------- 성찰 스냅샷 ----------
create table if not exists organism_reflections (
  id            bigserial primary key,
  cycle         int,
  top_interests jsonb,
  counts        jsonb,
  created_at    timestamptz not null default now()
);

-- ---------- RLS: 정책 없음 = service_role 전용 ----------
alter table organism_state        enable row level security;
alter table organism_observations enable row level security;
alter table organism_som          enable row level security;
alter table organism_runs         enable row level security;
alter table organism_reflections  enable row level security;

-- ---------- 원자적 상태 갱신 (CAS) ----------
-- 시간당/야간 워커가 겹쳐 돌아도 한쪽만 이긴다.
create or replace function organism_commit_state(
  p_version           int,
  p_cycle             int,
  p_interests         jsonb,
  p_visited           jsonb,
  p_transition_counts jsonb,
  p_last_topic        text,
  p_mode              text
) returns int
language plpgsql
security definer
set search_path = public
as $$
declare
  new_version int;
begin
  update organism_state
     set cycle             = p_cycle,
         interests         = p_interests,
         visited           = p_visited,
         transition_counts = p_transition_counts,
         last_topic        = p_last_topic,
         last_hourly_at    = case when p_mode in ('hourly','all')
                                  then now() else last_hourly_at end,
         last_nightly_at   = case when p_mode in ('nightly','all')
                                  then now() else last_nightly_at end,
         version           = version + 1,
         updated_at        = now()
   where id = 1 and version = p_version
  returning version into new_version;

  if new_version is null then
    raise exception 'organism_state version conflict (expected %)', p_version
      using errcode = '40001';
  end if;
  return new_version;
end;
$$;

-- ---------- 검증 ----------
select
  (select version from organism_state where id = 1)  as state_version,
  (select count(*) from organism_observations)       as observations,
  (select count(*) from organism_runs)               as runs;
