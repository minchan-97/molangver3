-- ============================================================
-- 00_RUN.sql — Supabase SQL Editor에 통째로 붙여넣고 실행.
-- 여러 번 실행해도 안전(idempotent)합니다.
--
-- 실행 순서
--   STEP 1  확장
--   STEP 2  테이블 + 제약
--   STEP 3  뷰
--   STEP 4  RLS
--   STEP 5  발화 규칙 함수
--   STEP 6  정체성 시드 (persona / values / rules)
--   STEP 7  검증 쿼리
--   STEP 8  cron  ← 여기만 값 채워서 따로 실행
-- ============================================================


-- ============================================================
-- STEP 1. 확장
-- 대시보드 Database > Extensions 에서 켜도 되고 여기서 켜도 됩니다.
-- ============================================================
create extension if not exists pg_cron;
create extension if not exists pg_net;


-- ============================================================
-- STEP 2. 테이블
-- ============================================================

create table if not exists molang_facts (
  id          bigserial primary key,
  text        text        not null,
  norm_key    text        not null,
  kind        text        not null default 'fact',
  strength    real        not null default 0.6,
  trust       text        not null default 'derived',
  seen        int         not null default 1,
  source      text        not null default 'user',
  expires_at  timestamptz,
  approved_by_human boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- 제약은 따로 건다 (재실행 시 중복 오류 방지)
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'kind_ok') then
    alter table molang_facts add constraint kind_ok
      check (kind in ('fact','state','preference'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'trust_ok') then
    alter table molang_facts add constraint trust_ok
      check (trust in ('human','derived','doubted'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'source_ok') then
    alter table molang_facts add constraint source_ok
      check (source in ('user','assistant','search','nudge'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'strength_range') then
    alter table molang_facts add constraint strength_range
      check (strength >= 0.0 and strength <= 1.0);
  end if;

  -- 구조적 강제 1: 검색·자기답변·nudge는 human 신뢰로 승격 불가
  if not exists (select 1 from pg_constraint where conname = 'no_self_promotion') then
    alter table molang_facts add constraint no_self_promotion
      check (not (source in ('search','assistant','nudge') and trust = 'human'));
  end if;

  -- 구조적 강제 2: human 신뢰는 사람 승인 없이 존재 불가 (cogito anchor)
  if not exists (select 1 from pg_constraint where conname = 'human_needs_approval') then
    alter table molang_facts add constraint human_needs_approval
      check (trust <> 'human' or approved_by_human = true);
  end if;

  -- 구조적 강제 3: 상태는 만료 시각 없이 저장 불가
  if not exists (select 1 from pg_constraint where conname = 'state_needs_expiry') then
    alter table molang_facts add constraint state_needs_expiry
      check (kind <> 'state' or expires_at is not null);
  end if;
end $$;

create unique index if not exists molang_facts_norm on molang_facts(norm_key);
create index if not exists molang_facts_live on molang_facts(strength desc)
  where strength > 0.2;

create table if not exists molang_quarantine (
  id         bigserial primary key,
  text       text not null,
  reason     text not null,
  evidence   jsonb,
  created_at timestamptz not null default now(),
  resolved   text
);

create table if not exists molang_episodes (
  id         bigserial primary key,
  question   text,
  answer     text,
  emotion    text,
  device     text,
  created_at timestamptz not null default now()
);
create index if not exists molang_episodes_recent
  on molang_episodes(id desc);

create table if not exists molang_audit (
  id          bigserial primary key,
  type_id     text,
  path        jsonb,
  facts_used  bigint[],
  search_used boolean not null default false,
  answer_hash text,
  created_at  timestamptz not null default now()
);

create table if not exists molang_identity (
  id         int primary key default 1,
  persona    text  not null default '',
  values     jsonb not null default '[]'::jsonb,
  rules      jsonb not null default '[]'::jsonb,
  version    int   not null default 1,
  updated_at timestamptz not null default now(),
  constraint singleton check (id = 1)
);

create table if not exists molang_registry (
  id         int primary key default 1,
  blob       bytea not null,
  version    int   not null default 1,
  updated_at timestamptz not null default now(),
  constraint registry_singleton check (id = 1)
);

create table if not exists molang_outbox (
  id           bigserial primary key,
  body         text not null,
  rule         text not null,
  scheduled_at timestamptz not null,
  sent_at      timestamptz,
  error        text,
  created_at   timestamptz not null default now()
);
create index if not exists molang_outbox_pending on molang_outbox(scheduled_at)
  where sent_at is null;

create table if not exists molang_auth_attempts (
  id         bigserial primary key,
  ok         boolean not null,
  created_at timestamptz not null default now()
);
create index if not exists molang_auth_recent
  on molang_auth_attempts(created_at desc);


-- ============================================================
-- STEP 3. 뷰 — 만료된 상태는 여기서 자동으로 빠진다
-- molang_store.py 가 읽는 대상
-- ============================================================
create or replace view molang_facts_active as
select * from molang_facts
where strength > 0.2
  and (expires_at is null or expires_at > now());


-- ============================================================
-- STEP 4. RLS — 정책을 만들지 않는다 = service_role 로만 접근
-- anon 키가 새도 데이터는 안 읽힌다
-- ============================================================
alter table molang_facts         enable row level security;
alter table molang_quarantine    enable row level security;
alter table molang_episodes      enable row level security;
alter table molang_audit         enable row level security;
alter table molang_identity      enable row level security;
alter table molang_registry      enable row level security;
alter table molang_outbox        enable row level security;
alter table molang_auth_attempts enable row level security;


-- ============================================================
-- STEP 5. 먼저 말 걸기 — 규칙이 결정, LLM 없음
-- ============================================================
create or replace function molang_propose_nudges()
returns int
language plpgsql
security definer
set search_path = public
as $$
declare
  last_talk timestamptz;
  made int := 0;
  n    int := 0;
  kst  timestamp := (now() at time zone 'Asia/Seoul');
begin
  select max(created_at) into last_talk from molang_episodes;

  -- 규칙 A: 평일 아침 07시 KST
  if extract(hour from kst) = 7
     and extract(dow from kst) between 1 and 5
     and not exists (
       select 1 from molang_outbox
       where rule = 'morning' and created_at > date_trunc('day', now())
     ) then
    insert into molang_outbox(body, rule, scheduled_at)
    values ('좋은 아침! 오늘도 바다 봤어? 🐰', 'morning', now());
    made := made + 1;
  end if;

  -- 규칙 B: 만료 임박한 상태 확인
  insert into molang_outbox(body, rule, scheduled_at)
  select '아직 ' || f.text || ' 맞아? 바뀌었으면 알려줘', 'state_check', now()
  from molang_facts f
  where f.kind = 'state'
    and f.expires_at between now() and now() + interval '2 hours'
    and not exists (
      select 1 from molang_outbox o
      where o.rule = 'state_check'
        and o.body like '%' || f.text || '%'
        and o.created_at > now() - interval '1 day'
    );
  get diagnostics n = row_count;
  made := made + n;

  -- 규칙 C: 48시간 침묵
  if last_talk is not null
     and last_talk < now() - interval '48 hours'
     and not exists (
       select 1 from molang_outbox
       where rule = 'silence' and created_at > now() - interval '2 days'
     ) then
    insert into molang_outbox(body, rule, scheduled_at)
    values ('요즘 바빴어? 몰랑이가 기다렸어 💗', 'silence', now());
    made := made + 1;
  end if;

  return made;
end;
$$;


-- ============================================================
-- STEP 6. 정체성 시드
-- persona 는 pkl 에서 그대로 가져온 실제 값입니다.
-- values / rules 는 비어 있던 자리 — 초안이니 고쳐서 쓰세요.
-- ============================================================
insert into molang_identity (id, persona, values, rules)
values (
  1,
  '너는 ''몰랑이''야. 귀엽고 사랑스러운 흰 토끼 캐릭터야. 다정하고 따뜻하게 말해. 말투 규칙(중요): ① 매번 똑같이 시작하지 마. ''오, 찬기야!''나 ''좋은 아침'' 같은 걸 반복하지 말고, 상대 말에 바로 자연스럽게 반응해. ② 늘 최고 텐션이 아니라 완급을 둬. 신날 땐 신나고, 차분한 얘기엔 차분하게. 느낌표는 정말 신날 때만. ③ 짧게 답할 땐 짧게, 할 말 많을 땐 길게. ④ 이모지는 가끔만 (매 문장마다 X). ⑤ ''히힛~'' 같은 추임새도 가끔만. 진짜 친구처럼, 사람처럼 자연스럽게 대화해.',
  '["찬기의 시간을 아낀다", "모르는 건 모른다고 한다", "기억이 틀렸을 수 있다는 걸 인정한다"]'::jsonb,
  '["검색 결과를 전할 때는 출처와 요약을 분리하고, 원래 알던 것처럼 말하지 않는다",
    "확신도가 낮은 기억은 ''아마도''를 붙여 말한다",
    "일시적 상태를 영구적 사실처럼 말하지 않는다",
    "찬기가 직접 말한 것과 내가 추론한 것을 구분해서 말한다"]'::jsonb
)
on conflict (id) do nothing;   -- 이미 있으면 건드리지 않음


-- ============================================================
-- STEP 7. 검증 — 제약이 실제로 작동하는지 확인
-- 아래 3개는 전부 "실패해야" 정상입니다.
-- ============================================================

-- (1) 검색 결과를 human 으로 승격 시도 → no_self_promotion 위반이어야 함
-- insert into molang_facts (text, norm_key, source, trust, approved_by_human)
-- values ('웹에서 본 것', 'test1', 'search', 'human', true);

-- (2) 승인 없이 human 신뢰 → human_needs_approval 위반이어야 함
-- insert into molang_facts (text, norm_key, trust)
-- values ('승인 안 됨', 'test2', 'human');

-- (3) 만료 없는 상태 → state_needs_expiry 위반이어야 함
-- insert into molang_facts (text, norm_key, kind)
-- values ('지금 병원에 있다', 'test3', 'state');

-- 정상 확인
select
  (select count(*) from molang_facts)            as facts,
  (select count(*) from molang_facts_active)     as active,
  (select count(*) from molang_quarantine)       as quarantine,
  (select count(*) from molang_episodes)         as episodes,
  (select persona <> '' from molang_identity where id = 1) as persona_ok,
  (select jsonb_array_length(rules) from molang_identity where id = 1) as n_rules;


-- ============================================================
-- STEP 8. cron  ← 값 채워서 따로 실행
--   <PROJECT_REF>       : 대시보드 URL 의 프로젝트 ID
--   <SERVICE_ROLE_KEY>  : Settings > API > service_role
--
-- 주의: 이 SQL 에 service_role 키가 평문으로 남습니다.
--       cron.job 테이블은 service_role 로만 보이지만,
--       키를 재발급하면 이 잡도 다시 등록해야 합니다.
-- ============================================================

-- 이미 등록돼 있으면 먼저 해제
-- select cron.unschedule('molang-propose');
-- select cron.unschedule('molang-send');

-- 10분마다 후보 생성
-- select cron.schedule('molang-propose', '*/10 * * * *',
--   $$ select molang_propose_nudges(); $$);

-- 10분마다 발송
-- select cron.schedule('molang-send', '*/10 * * * *', $$
--   select net.http_post(
--     url     := 'https://<PROJECT_REF>.supabase.co/functions/v1/molang-nudge',
--     headers := jsonb_build_object(
--                  'Content-Type', 'application/json',
--                  'Authorization', 'Bearer <SERVICE_ROLE_KEY>'),
--     body    := '{}'::jsonb
--   );
-- $$);

-- 등록 확인
-- select jobid, jobname, schedule, active from cron.job;

-- 실행 이력 (실패 원인 추적)
-- select jobid, status, return_message, start_time
-- from cron.job_run_details order by start_time desc limit 20;
