"""
molang_store.py — IdentityMemory를 Supabase로 대체하는 어댑터.

UnifiedIdentity.think() / molang_self.build_self_model() 이 읽는 속성을
그대로 흉내내는 덕타이핑 드롭인이다. 엔진 코드는 손대지 않는다.

  u.identity = SupabaseIdentity(sb)   # 이 한 줄로 교체

핵심 원칙:
  1. 출처가 'user'가 아니면 사실이 될 수 없다. (검색·자기답변·nudge 격리)
  2. 쓰기는 변경분만. 매 턴 전체 동기화는 하지 않는다.
  3. 만료된 상태는 프롬프트에 주입되지 않는다.
"""
from __future__ import annotations
import hashlib
import time
from datetime import datetime, timedelta, timezone

from molang_norm import (normalize, jaccard, classify_kind,
                         is_assistant_echo, TTL)

KST = timezone(timedelta(hours=9))

TRUST_STRENGTH = {'human': 1.0, 'derived': 0.6, 'doubted': 0.2}

# 흡수 가능한 유일한 출처
ABSORBABLE = {'user'}


def _closer_to_answer(fact: str, question: str, answer: str) -> bool:
    """
    사실이 사용자의 말이 아니라 몰랑이의 답변에서 나온 것인가.

    백업에서 확인된 실제 오염:
      질문 "너가 공부한거 말이야" → 몰랑이가 자기 공부를 답함
      → 저장된 사실 "사용자는 새로운 공부법과 시간 관리에 대해 연구했다"
    주어만 바꿔치기된 것이므로, 낱말 겹침으로 잡을 수 있다.
    """
    import re
    w = lambda t: set(re.findall(r'[가-힣A-Za-z]{2,}', t or ''))
    f, q, a = w(fact), w(question), w(answer)
    f = f - {'사용자', '사람', '그것', '이것'}
    if not f:
        return False
    in_q = len(f & q) / len(f)
    in_a = len(f & a) / len(f)
    # 답변에는 많이 겹치고 사용자 말에는 거의 안 겹치면 = 몰랑이 얘기
    return in_a >= 0.5 and in_a > in_q * 1.5


class RejectedWrite(Exception):
    """격리 규칙에 의해 차단된 쓰기."""


class SupabaseIdentity:
    def __init__(self, sb, max_facts_in_prompt: int = 30,
                 recent_episodes: int = 10):
        self.sb = sb
        self.max_facts = max_facts_in_prompt
        self.recent_episodes = recent_episodes

        self._facts: list[dict] = []
        self._episodic: list[str] = []
        self.persona: str = ''
        self.values: list = []
        self.judgment_rules: list = []
        self.revisions: list = []
        self._dirty: dict[int, dict] = {}
        self._identity_version: int = 1
        self.reload()

    # ---------- 로드 ----------

    def reload(self):
        # maybe_single()은 행이 0개일 때 라이브러리 판에 따라 예외를 던지거나
        # None을 돌려준다. 첫 실행(빈 테이블)에서 앱이 죽지 않도록 감싸고,
        # 없으면 기본 행을 만들어 둔다.
        idn = None
        try:
            res = self.sb.table('molang_identity').select('*').eq('id', 1) \
                      .limit(1).execute()
            rows = getattr(res, 'data', None) or []
            idn = rows[0] if rows else None
        except Exception:
            idn = None
        if idn is None:
            try:
                self.sb.table('molang_identity').insert(
                    {'id': 1, 'persona': '', 'values': [], 'rules': [],
                     'version': 1}).execute()
            except Exception:
                pass
        if idn:
            self.persona = idn.get('persona') or ''
            self.values = idn.get('values') or []
            self.judgment_rules = idn.get('rules') or []
            self._identity_version = idn.get('version', 1)

        # 만료·소멸 제외된 뷰에서만 읽는다
        try:
            self._facts = self.sb.table('molang_facts_active') \
                .select('id,text,norm_key,kind,strength,trust,seen,source,expires_at') \
                .order('strength', desc=True).limit(400).execute().data or []
        except Exception as e:      # 뷰가 아직 없으면 알려주고 빈 상태로 시작
            self._facts = []
            self._load_error = f"molang_facts_active 읽기 실패: {e}"

        try:
            eps = self.sb.table('molang_episodes') \
                .select('question,answer').order('id', desc=True) \
                .limit(self.recent_episodes).execute().data or []
        except Exception:
            eps = []
        self._episodic = [f"Q: {(e.get('question') or '')[:60]} / "
                          f"A: {(e.get('answer') or '')[:80]}"
                          for e in reversed(eps)]

    # ---------- 엔진 호환 속성 ----------

    @property
    def learned_facts(self):
        """molang_self.build_self_model()이 읽는 형태 그대로."""
        return self._facts

    @property
    def episodic(self):
        return self._episodic

    def _fact_texts(self):
        return [f['text'] for f in self._facts if f['strength'] > 0.2]

    # ---------- 프롬프트 주입 ----------

    def to_system_prompt(self, base: str = '') -> str:
        parts = []
        if self.persona:
            parts.append(f"[너의 정체성]\n{self.persona}")
        if self.values:
            vs = "\n".join(f"- {v}" for v in self.values)
            parts.append(f"[너의 가치관 — 항상 이에 부합하게 답하라]\n{vs}")
        if self.judgment_rules:
            rs = "\n".join(f"- {r}" for r in self.judgment_rules)
            parts.append(f"[너의 판단 기준 — 이 기준으로 판단하라]\n{rs}")

        items = []
        for f in self._facts:
            s = f.get('strength', 0.6)
            if s <= 0.2:
                continue
            # 신뢰 계층이 표기를 결정한다 (strength 단독이 아니라)
            if f.get('trust') == 'human':
                tag = ''
            elif s >= 0.8:
                tag = ''
            else:
                tag = ' (아마도)'
            items.append((TRUST_STRENGTH.get(f.get('trust'), 0.6) * s,
                          f"- {f['text']}{tag}"))
        items.sort(key=lambda x: -x[0])
        if items:
            fs = "\n".join(t for _, t in items[:self.max_facts])
            parts.append(f"[네가 축적한 지식]\n{fs}")

        if self._episodic:
            es = "\n".join(f"- {e}" for e in self._episodic)
            parts.append(f"[최근 대화에서 형성된 맥락]\n{es}")

        block = "\n\n".join(parts)
        if base:
            return (f"{base}\n\n=== 아래는 너의 지속적 정체성이다. "
                    f"매 답변에서 유지하라 ===\n{block}")
        return block

    # ---------- 흡수 ----------

    def absorb(self, question: str, answer: str, learned: str = '',
               consolidate_fn=None, source: str = 'user',
               emotion: str = None, device: str = None):
        """
        source != 'user' 이면 에피소드만 남기고 사실은 만들지 않는다.

        주의: 원본 unified_identity.react()는 learned=rec.answer[:80] 로
        몰랑이 자기 답변을 그대로 넘긴다. 그게 오염의 직접 원인이었다.
        여기서는 is_assistant_echo()로 한 번 더 막는다.
        """
        self.sb.table('molang_episodes').insert({
            'question': question[:2000],
            'answer': (answer or '')[:4000],
            'emotion': emotion,
            'device': device,
        }).execute()
        self._episodic.append(f"Q: {question[:60]} / A: {(answer or '')[:80]}")
        self._episodic = self._episodic[-self.recent_episodes:]

        if source not in ABSORBABLE:
            return   # 검색·nudge·자기답변은 여기서 끝

        if learned:
            self._reinforce_or_add(learned, source='user')

        if consolidate_fn is not None:
            try:
                result = consolidate_fn(question, answer, self._fact_texts())
                if isinstance(result, dict):
                    fact = (result.get('fact') or '').strip()
                    conflict = result.get('conflicts_with')
                    if fact and fact.upper() != 'NONE':
                        # 사실이 사용자 말보다 몰랑이 답변에 더 가까우면
                        # 그건 몰랑이가 자기 얘기를 한 것이다 → 사용자 사실이 아님.
                        if _closer_to_answer(fact, question, answer):
                            self._quarantine(
                                fact, 'assistant_echo',
                                {'question': question[:200],
                                 'answer': (answer or '')[:200]})
                        else:
                            if conflict:
                                self._weaken(conflict)
                            self._reinforce_or_add(fact, source='user')
                elif result and str(result).strip().upper() != 'NONE':
                    self._reinforce_or_add(str(result).strip(), source='user')
            except Exception:
                pass

    # ---------- 사실 갱신 ----------

    def _reinforce_or_add(self, fact: str, source: str = 'user',
                          step: float = 0.25):
        fact = fact.strip()
        if not fact:
            return

        # 방어선 1: 자기 답변 에코는 검역소로
        if is_assistant_echo(fact):
            self._quarantine(fact, 'assistant_echo', {'source': source})
            return

        # 방어선 2: 근접 중복은 신규 삽입이 아니라 강화
        for f in self._facts:
            if jaccard(fact, f['text']) >= 0.75:
                new_s = min(1.0, f['strength'] + step)
                f['strength'] = new_s
                f['seen'] = f.get('seen', 1) + 1
                self.sb.table('molang_facts').update({
                    'strength': new_s, 'seen': f['seen'],
                    'updated_at': _now_iso(),
                }).eq('id', f['id']).execute()
                if normalize(fact) != f['norm_key']:
                    self._quarantine(fact, 'near_duplicate',
                                     {'merged_into': f['text']})
                return

        kind = classify_kind(fact)
        expires = None
        if kind == 'state':
            expires = (datetime.now(KST) + TTL['state']).isoformat()

        row = {
            'text': fact,
            'norm_key': normalize(fact),
            'kind': kind,
            'strength': 0.6,
            'trust': 'derived',        # 새 사실은 절대 human이 아니다
            'seen': 1,
            'source': source,
            'expires_at': expires,
            'approved_by_human': False,
        }
        try:
            res = self.sb.table('molang_facts').insert(row).execute()
            if res.data:
                self._facts.append(res.data[0])
        except Exception as e:
            # norm_key unique 충돌 = 이미 아는 사실
            if 'duplicate' not in str(e).lower():
                raise

    def _weaken(self, fact_text: str, step: float = 0.3):
        for f in list(self._facts):
            if jaccard(fact_text, f['text']) >= 0.75:
                new_s = f['strength'] - step
                if new_s > 0.2:
                    f['strength'] = new_s
                    self.sb.table('molang_facts').update({
                        'strength': new_s, 'updated_at': _now_iso()
                    }).eq('id', f['id']).execute()
                else:
                    # human 승인된 사실은 자동 폐기하지 않는다 (앵커 보호)
                    if f.get('trust') == 'human':
                        self._quarantine(
                            fact_text, 'conflicts_with_anchor',
                            {'anchor': f['text']})
                        continue
                    self.sb.table('molang_facts').update({
                        'strength': 0.0, 'updated_at': _now_iso()
                    }).eq('id', f['id']).execute()
                    self._facts.remove(f)
                return

    def _quarantine(self, text: str, reason: str, evidence: dict = None):
        self.sb.table('molang_quarantine').insert({
            'text': text[:2000], 'reason': reason,
            'evidence': evidence or {},
        }).execute()

    # ---------- 사람 승인 (cogito anchor) ----------

    def approve(self, fact_id: int):
        """사람이 승인해야만 human 신뢰로 올라간다."""
        self.sb.table('molang_facts').update({
            'trust': 'human', 'strength': 1.0,
            'approved_by_human': True, 'updated_at': _now_iso(),
        }).eq('id', fact_id).execute()
        self.reload()

    def doubt(self, fact_id: int):
        self.sb.table('molang_facts').update({
            'trust': 'doubted', 'strength': 0.2, 'updated_at': _now_iso(),
        }).eq('id', fact_id).execute()
        self.reload()

    def pending_quarantine(self, limit: int = 50):
        return self.sb.table('molang_quarantine').select('*') \
            .is_('resolved', 'null').order('id', desc=True) \
            .limit(limit).execute().data or []

    # ---------- 감사 로그 ----------

    def audit(self, type_id: str, path, facts_used=None,
              search_used: bool = False, answer: str = ''):
        self.sb.table('molang_audit').insert({
            'type_id': type_id,
            'path': path if isinstance(path, (list, dict)) else str(path),
            'facts_used': facts_used or [],
            'search_used': search_used,
            'answer_hash': hashlib.sha256(
                (answer or '').encode()).hexdigest()[:32],
        }).execute()

    # ---------- 정체성 뼈대 저장 (낙관적 잠금) ----------

    def save_identity(self):
        res = self.sb.table('molang_identity').update({
            'persona': self.persona,
            'values': self.values,
            'rules': self.judgment_rules,
            'version': self._identity_version + 1,
            'updated_at': _now_iso(),
        }).eq('id', 1).eq('version', self._identity_version).execute()
        if not res.data:
            raise RuntimeError(
                '다른 기기에서 정체성이 먼저 수정됐습니다. reload() 후 재시도.')
        self._identity_version += 1


def _now_iso():
    return datetime.now(KST).isoformat()
