-- ============================================================
-- 몰랑이 Supabase 스키마
-- 설계 원칙: Supabase는 "침전물 저장소"다. 판단은 로컬 엔진이 한다.
--   - 신뢰 3계층(TRUST_HUMAN/DERIVED/DOUBTED)을 DB 제약으로 강제
--   - 흡수 가능 출처를 DB 제약으로 강제 (검색/자기답변은 승격 불가)
--   - 모든 답변 생성은 audit_log를 남긴다 (감사 로그 청구항 실물)
-- ============================================================

-- ---------- 1. 사실 (learned_facts) ----------
create table if not exists molang_facts (
  id          bigserial primary key,
  text        text        not null,
  norm_key    text        not null,          -- 정규화 키. 접두어 30자 비교 대체
  kind        text        not null default 'fact',
  strength    real        not null default 0.6,
  trust       text        not null default 'derived',
  seen        int         not null default 1,
  source      text        not null default 'user',
  expires_at  timestamptz,                   -- 상태(state)는 반드시 채운다
  approved_by_human boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),

  constraint kind_ok   check (kind   in ('fact','state','preference')),
  constraint trust_ok  check (trust  in ('human','derived','doubted')),
  constraint source_ok check (source in ('user','assistant','search','nudge')),
  constraint strength_range check (strength >= 0.0 and strength <= 1.0),

  -- 구조적 강제 1: 검색 결과와 자기 답변은 절대 human 신뢰로 승격 불가
  constraint no_self_promotion check (
    not (source in ('search','assistant','nudge') and trust = 'human')
  ),
  -- 구조적 강제 2: human 신뢰는 사람 승인 없이 존재할 수 없다 (cogito anchor)
  constraint human_needs_approval check (
    trust <> 'human' or approved_by_human = true
  ),
  -- 구조적 강제 3: 상태는 만료 시각이 없으면 저장 불가
  constraint state_needs_expiry check (
    kind <> 'state' or expires_at is not null
  )
);

create unique index if not exists molang_facts_norm on molang_facts(norm_key);
create index if not exists molang_facts_live on molang_facts(strength desc)
  where strength > 0.2;

-- 만료된 상태는 프롬프트에서 자동 제외되는 뷰
create or replace view molang_facts_active as
select * from molang_facts
where strength > 0.2
  and (expires_at is null or expires_at > now());

-- ---------- 2. 검역소 (사람 승인 대기) ----------
create table if not exists molang_quarantine (
  id         bigserial primary key,
  text       text not null,
  reason     text not null,        -- 'assistant_echo' | 'near_duplicate' | 'stale_state'
  evidence   jsonb,
  created_at timestamptz not null default now(),
  resolved   text                  -- null | 'approved' | 'rejected' | 'merged'
);

-- ---------- 3. 에피소드 ----------
create table if not exists molang_episodes (
  id         bigserial primary key,
  question   text,
  answer     text,
  emotion    text,
  device     text,                 -- 'phone' | 'pc' — 기기 간 연속성 확인용
  created_at timestamptz not null default now()
);

-- ---------- 4. 감사 로그 (특허 청구항 실물 증거) ----------
create table if not exists molang_audit (
  id          bigserial primary key,
  type_id     text,                -- 판별된 사고 유형
  path        jsonb,               -- 트리 순회 경로
  facts_used  bigint[],            -- 주입된 사실 id
  search_used boolean not null default false,
  answer_hash text,
  created_at  timestamptz not null default now()
);

-- ---------- 5. 정체성 뼈대 (persona / values / rules) ----------
create table if not exists molang_identity (
  id         int primary key default 1,
  persona    text not null default '',
  values     jsonb not null default '[]'::jsonb,
  rules      jsonb not null default '[]'::jsonb,
  version    int  not null default 1,     -- 낙관적 잠금
  updated_at timestamptz not null default now(),
  constraint singleton check (id = 1)
);

-- ---------- 6. 트리 레지스트리 (구조는 pkl 유지) ----------
create table if not exists molang_registry (
  id         int primary key default 1,
  blob       bytea not null,
  version    int   not null default 1,
  updated_at timestamptz not null default now(),
  constraint registry_singleton check (id = 1)
);

-- ---------- 7. 발신함 (먼저 말 걸기) ----------
create table if not exists molang_outbox (
  id           bigserial primary key,
  body         text not null,
  rule         text not null,      -- 어떤 규칙이 이 발화를 만들었나
  scheduled_at timestamptz not null,
  sent_at      timestamptz,
  error        text,
  created_at   timestamptz not null default now()
);

create index if not exists molang_outbox_pending on molang_outbox(scheduled_at)
  where sent_at is null;

-- ---------- 8. 로그인 시도 (무차별 대입 방어) ----------
create table if not exists molang_auth_attempts (
  id         bigserial primary key,
  ok         boolean not null,
  created_at timestamptz not null default now()
);

-- ============================================================
-- RLS: 익명 키가 새도 데이터는 못 읽는다
-- ============================================================
alter table molang_facts       enable row level security;
alter table molang_quarantine  enable row level security;
alter table molang_episodes    enable row level security;
alter table molang_audit       enable row level security;
alter table molang_identity    enable row level security;
alter table molang_registry    enable row level security;
alter table molang_outbox      enable row level security;
alter table molang_auth_attempts enable row level security;
-- 정책을 하나도 만들지 않는다 = service_role 키로만 접근 가능.
-- Streamlit 서버에서만 service_role을 쓰고, 절대 클라이언트로 내보내지 않는다.

-- ============================================================
-- 먼저 말 걸기: 규칙 기반 후보 생성 (LLM 없음)
-- 발화 여부를 구조가 결정한다. 문장 톤만 나중에 입힌다.
-- ============================================================
create or replace function molang_propose_nudges()
returns int
language plpgsql
security definer
as $$
declare
  last_talk timestamptz;
  n int := 0;
  kst timestamptz := now() at time zone 'Asia/Seoul';
begin
  select max(created_at) into last_talk from molang_episodes;

  -- 규칙 A: 아침 인사 (평일 07:10 KST, 그날 아직 안 보냈으면)
  if extract(hour from kst) = 7
     and extract(dow from kst) between 1 and 5
     and not exists (
       select 1 from molang_outbox
       where rule = 'morning'
         and created_at > date_trunc('day', now())
     ) then
    insert into molang_outbox(body, rule, scheduled_at)
    values ('좋은 아침! 오늘도 바다 봤어? 🐰', 'morning', now());
    n := n + 1;
  end if;

  -- 규칙 B: 만료 임박한 상태 확인 (아직 유효한가?)
  insert into molang_outbox(body, rule, scheduled_at)
  select '아직 ' || f.text || ' 맞아? 바뀌었으면 알려줘!', 'state_check', now()
  from molang_facts f
  where f.kind = 'state'
    and f.expires_at between now() and now() + interval '2 hours'
    and not exists (
      select 1 from molang_outbox o
      where o.rule = 'state_check' and o.body like '%' || f.text || '%'
        and o.created_at > now() - interval '1 day'
    );
  get diagnostics n = row_count;

  -- 규칙 C: 48시간 침묵
  if last_talk is not null and last_talk < now() - interval '48 hours'
     and not exists (
       select 1 from molang_outbox
       where rule = 'silence' and created_at > now() - interval '2 days'
     ) then
    insert into molang_outbox(body, rule, scheduled_at)
    values ('요즘 바빴어? 몰랑이가 기다렸어 💗', 'silence', now());
  end if;

  return n;
end;
$$;

-- ============================================================
-- cron: 후보 생성 + 발송 트리거
-- Supabase 대시보드에서 pg_cron, pg_net 확장을 먼저 켤 것
-- ============================================================
-- create extension if not exists pg_cron;
-- create extension if not exists pg_net;

-- 10분마다 후보 생성
-- select cron.schedule('molang-propose', '*/10 * * * *',
--   $$ select molang_propose_nudges(); $$);

-- 10분마다 Edge Function 호출해서 발송
-- select cron.schedule('molang-send', '*/10 * * * *', $$
--   select net.http_post(
--     url     := 'https://<PROJECT_REF>.supabase.co/functions/v1/molang-nudge',
--     headers := jsonb_build_object(
--                  'Content-Type','application/json',
--                  'Authorization','Bearer <SERVICE_ROLE_KEY>')
--   );
-- $$);
