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


# molang_facts.source_ok 제약과 같은 값 (DB 와 코드가 어긋나면 저장이 통째로 실패)
#
# **여기를 늘릴 때는 DB 제약도 함께 늘려야 한다.**
# 실제로 travel·peer 를 코드에만 더하고 이 목록을 안 늘려서,
# 모든 사실이 조용히 'user' 로 바뀌었다 (306건 전부). 그 탓에
# 출처별로 다르게 옅어지는 것도, 겪음 판정도 전부 작동하지 않았다.
ALLOWED_SOURCES = {
    'user', 'assistant', 'search', 'nudge',
    'travel',    # 여행에서 겪은 일
    'home',      # 집에서 일어난 일
    'land',      # 바깥 나들이
    'dream',     # 꿈
    'peer',      # 피우피우와의 대화
    'village',   # 마을 사람에게 들은 것
    'self',      # 스스로 알아차린 것
}


# 몰랑이가 자기 느낌을 말한 것을 사용자 사실로 적으면 기억의 주인이 바뀐다.
# ("바다의 짙은 파란색이 마음을 편안하게 해줬어" → '사용자는 …을 좋아한다')
# 낱말 겹침만으로는 못 잡는다. 사용자가 바다 얘기를 꺼냈다면 양쪽에 다 있으니까.
# 그래서 **그 문장이 원래 어느 쪽에 있었는지**를 문장 단위로 본다.
_SELF_MARK = ("나는", "내가", "나도", "난 ", "내 ", "몰랑이는", "몰랑이가")


def _from_assistant(fact: str, question: str, answer: str) -> bool:
    """사실이 몰랑이 답변의 **한 문장**에서 거의 그대로 온 것인가."""
    import re
    norm = lambda t: set(re.findall(r'[가-힣A-Za-z]{2,}', t or ''))
    f = norm(fact) - {'사용자', '찬기', '그는'}
    if not f:
        return False
    for sent in re.split(r'[.!?\n]', answer or ''):
        sw = norm(sent)
        if not sw:
            continue
        cover = len(f & sw) / len(f)
        if cover >= 0.6:
            # 그 문장이 몰랑이 자기 얘기였나 (주어 표시)
            if any(m in sent for m in _SELF_MARK):
                return True
            # 사용자 말에는 없던 내용인가
            if len(f & norm(question)) / len(f) < 0.4:
                return True
    return False


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
    def __init__(self, sb, owner: str = 'molang', max_facts_in_prompt: int = 90,
                 recent_episodes: int = 10):
        self.sb = sb
        # 한 저장소에 여러 존재가 산다. owner 로 기억을 나눈다.
        # (몰랑이와 피우피우가 같은 표를 쓰되 서로의 기억을 침범하지 않게)
        self.owner = owner
        self.max_facts = max_facts_in_prompt
        self._recall = None            # 사실 지도 (기억이 많아지면 만든다)
        self._recall_n = 0
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
            res = self.sb.table('molang_identity').select('*') \
                      .eq('owner', self.owner).limit(1).execute()
            rows = getattr(res, 'data', None) or []
            idn = rows[0] if rows else None
        except Exception:
            idn = None
        if idn is None:
            try:
                self.sb.table('molang_identity').insert(
                    {'owner': self.owner, 'persona': '', 'values': [],
                     'rules': [], 'version': 1}).execute()
            except Exception:
                pass
        if idn:
            self.persona = idn.get('persona') or ''
            self.values = idn.get('values') or []
            self.judgment_rules = idn.get('rules') or []
            self._identity_version = idn.get('version', 1)

        # 만료·소멸 제외된 뷰에서만 읽는다
        self._recall = None            # 사실이 바뀌면 지도를 다시 만든다
        try:
            # **최근순으로 읽는다.**
            #
            # 예전에는 강도순 상위 400건이었다. 그러면 사실이 400을 넘는
            # 순간 **새로 들어온 것부터 잘린다** (갓 들어온 사실은 0.6).
            # 실제로 사실 수가 400에서 멈춰 보였고, 어제 한 말이
            # 아예 안 올라왔다.
            self._facts = self.sb.table('molang_facts_active') \
                .select('id,text,norm_key,kind,strength,trust,seen,source,'
                        'expires_at,owner,updated_at,created_at') \
                .eq('owner', self.owner) \
                .order('updated_at', desc=True).limit(400).execute().data or []

            # 다만 **사람이 승인한 것**은 오래됐다고 잘리면 안 된다.
            # 그건 이 아이가 기댈 수 있는 몇 안 되는 바닥이다.
            try:
                anchors = self.sb.table('molang_facts_active') \
                    .select('id,text,norm_key,kind,strength,trust,seen,source,'
                            'expires_at,owner,updated_at,created_at') \
                    .eq('owner', self.owner).eq('trust', 'human') \
                    .limit(120).execute().data or []
                have = {f.get('id') for f in self._facts}
                self._facts += [f for f in anchors if f.get('id') not in have]
            except Exception:
                pass
        except Exception as e:      # 뷰가 아직 없으면 알려주고 빈 상태로 시작
            self._facts = []
            self._load_error = f"molang_facts_active 읽기 실패: {e}"

        try:
            eps = self.sb.table('molang_episodes') \
                .select('question,answer').eq('owner', self.owner) \
                .order('id', desc=True) \
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

    def to_system_prompt(self, base: str = '', question: str = '') -> str:
        """
        정체성 프롬프트.

        사실이 많아지면 상위 N개만 넣게 되는데, 그러면 '축구팀 기억나?' 처럼
        **지금 묻는 것**에 해당하는 사실이 강도가 낮다는 이유로 잘린다.
        (실제로 42건 중 30개만 들어가 축구 기억이 빠졌다)
        그래서 질문과 낱말이 겹치는 사실은 먼저 넣는다.
        """
        parts = []
        if self.persona:
            parts.append(f"[너의 정체성]\n{self.persona}")
        if self.values:
            vs = "\n".join(f"- {v}" for v in self.values)
            parts.append(f"[너의 가치관 — 항상 이에 부합하게 답하라]\n{vs}")
        if self.judgment_rules:
            rs = "\n".join(f"- {r}" for r in self.judgment_rules)
            parts.append(f"[너의 판단 기준 — 이 기준으로 판단하라]\n{rs}")

        import re as _re
        qtok = {w for w in _re.findall(r'[가-힣A-Za-z]{2,}', question or '')}
        qstem = {w[:2] for w in qtok}

        # 사실이 많아지면 강도순 상위 N개로는 '지금 필요한 기억'을 놓친다.
        # 지도(SOM)로 질문에 가까운 것부터 꺼낸다. 적을 땐 그대로 전부.
        pool = self._facts
        try:
            import recall
            if len(self._facts) >= recall.MIN_FOR_SOM and question:
                if getattr(self, '_recall', None) is None or \
                        self._recall_n != len(self._facts):
                    self._recall = recall.FactRecall(self._facts)
                    self._recall_n = len(self._facts)
                # 마르코프를 함께 넘긴다 — 질문의 낱말에서 **이어지는**
                # 낱말이 든 사실까지 끌어오기 위해서다.
                _mkd = None
                try:
                    _r = (self.sb.table("molang_markov").select("data")
                          .eq("id", 1).limit(1).execute().data) or []
                    _mkd = (_r[0].get("data") if _r else None)
                except Exception:
                    _mkd = None
                pool = self._recall.recall(question, k=self.max_facts,
                                           markov=_mkd)
        except Exception:
            pool = self._facts

        # **꺼내 쓴 것은 다시 굳는다.**
        # 옅어지기만 하고 굳는 길이 없으면 오래 둔 기억은 모두 흐려진다.
        # 실제로 대화에 들어간 것만, 그리고 이미 흐려진 것만 올린다.
        try:
            import belief_decay as _bd
            _used = [f for f in pool[:8]
                     if 0.2 < float(f.get("strength") or 0) < 1.0]
            if _used:
                _bd.touch(self.sb, _used)
        except Exception:
            pass


        items = []
        for f in pool:
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
            score = TRUST_STRENGTH.get(f.get('trust'), 0.6) * s
            if qtok:                      # 지금 묻는 것과 겹치면 앞으로
                ftok = set(_re.findall(r'[가-힣A-Za-z]{2,}', f['text']))
                if qtok & ftok or qstem & {w[:2] for w in ftok}:
                    score += 10.0
            items.append((score, f"- {f['text']}{tag}"))
        items.sort(key=lambda x: -x[0])
        if items:
            # 사실이 상한을 넘으면, 무엇이 잘렸는지 알 수 있게 알려준다.
            # (조용히 잘리면 "왜 기억을 못 하지?" 의 원인을 영영 못 찾는다)
            shown = items[:self.max_facts]
            fs = "\n".join(t for _, t in shown)
            more = len(items) - len(shown)
            tail = f"\n(그 밖에 {more}가지를 더 알고 있지만 지금은 떠오르지 않는다)" if more else ""
            parts.append(f"[네가 축적한 지식]\n{fs}{tail}")

        # **어긋나는 기억은 숨기지 않는다.**
        # 하나를 조용히 고르면 왜 그렇게 답했는지 기록에 안 남고,
        # 그건 아는 척에 가깝다. 둘 다 두고 모른다고 말할 수 있게 한다.
        try:
            import recall as _rc
            _cn = _rc.conflict_note(pool)
            if _cn:
                parts.append(_cn.rstrip())
        except Exception:
            pass

        if self._episodic:
            es = "\n".join(f"- {e}" for e in self._episodic)
            parts.append(f"[최근 대화에서 형성된 맥락]\n{es}")

        block = "\n\n".join(parts)
        if base:
            return (f"{base}\n\n=== 아래는 너의 지속적 정체성이다. "
                    f"매 답변에서 유지하라 ===\n{block}")
        return block

    # ---------- 흡수 ----------

    def absorb(self, question: str, answer: str, learned: str = '', place: str = '',
               consolidate_fn=None, source: str = 'user',
               emotion: str = None, device: str = None):
        """
        source != 'user' 이면 에피소드만 남기고 사실은 만들지 않는다.

        주의: 원본 unified_identity.react()는 learned=rec.answer[:80] 로
        몰랑이 자기 답변을 그대로 넘긴다. 그게 오염의 직접 원인이었다.
        여기서는 is_assistant_echo()로 한 번 더 막는다.
        """
        # "~할 거야" 는 사실이 아니라 **기다릴 거리**로 따로 적어둔다.
        # 며칠 뒤에 어떻게 됐는지 물어보기 위해서다.
        try:
            import caring as _cr
            _cr.remember_plan(self.sb, question or "", owner=self.owner)
        except Exception:
            pass

        self.sb.table('molang_episodes').insert({
            'owner': self.owner, 'place': place or getattr(self, 'place', None),
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
                        if (_closer_to_answer(fact, question, answer)
                                or _from_assistant(fact, question, answer)):
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
                          speaker: str = '',
                          step: float = 0.25):
        fact = fact.strip()
        if not fact:
            return
        # source 는 '어디서 왔나'만 받는다 (DB 제약 source_ok).
        # 'human'(신뢰도 값)이나 'migration' 같은 걸 넣으면 통째로 거부된다.
        # 부르는 쪽이 옛 버전이어도 여기서 막는다.
        if source not in ALLOWED_SOURCES:
            source = 'user' 

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

        # 들어온 것과 부딪히는 기존 사실이 있으면 **양쪽 다** 깎는다.
        # 어느 쪽이 맞는지 아직 모르기 때문이다. 나중에 한쪽이 다시
        # 확인되면 자연히 갈린다. (지우지 않는 이유이기도 하다)
        try:
            import belief_decay as _bd
            _bd.apply_conflict(self.sb, fact, self._facts,
                               log=lambda *a: None)
        except Exception:
            pass

        kind = classify_kind(fact)
        expires = None
        if kind == 'state':
            expires = (datetime.now(KST) + TTL['state']).isoformat()

        # 이 말이 **누구에 대한 것인지**를 함께 남긴다.
        # owner(저장소)와 about(대상)은 다르다. 섞으면 "부산 일광에 산다" 가
        # 자기 사실처럼 읽힌다.
        try:
            import aboutness as _ab
            _about, _why = _ab.judge(fact, source, speaker or "")
        except Exception:
            _about, _why = "unknown", ""

        row = {
            'text': fact,
            'norm_key': normalize(fact),
            'about': _about,
            'kind': kind,
            'strength': 0.6,
            'trust': 'derived',        # 새 사실은 절대 human이 아니다
            'seen': 1,
            'source': source,
            'expires_at': expires,
            'approved_by_human': False,
        }
        try:
            row = {**row, 'owner': self.owner}
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
        """
        격리. **같은 내용을 다시 넣지 않는다.**
        같은 답변이 매 턴 다시 격리되면 검토함이 같은 문장으로 채워지고,
        승인해도 줄지 않는다(실제로 같은 문장이 4번 쌓였다).
        """
        body = (text or '')[:2000]
        try:
            key = normalize(body)[:120]
            rows = (self.sb.table('molang_quarantine').select('id,text')
                    .order('id', desc=True).limit(80).execute().data) or []
            for r in rows:
                if normalize(r.get('text') or '')[:120] == key:
                    return          # 이미 있다 (처리됐든 대기 중이든)
        except Exception:
            pass
        self.sb.table('molang_quarantine').insert({
            'text': body, 'reason': reason, 'evidence': evidence or {},
            'owner': self.owner,
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
            .eq('owner', self.owner).is_('resolved', 'null').order('id', desc=True) \
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
        }).eq('owner', self.owner).eq('version', self._identity_version).execute()
        if not res.data:
            raise RuntimeError(
                '다른 기기에서 정체성이 먼저 수정됐습니다. reload() 후 재시도.')
        self._identity_version += 1


def _now_iso():
    return datetime.now(KST).isoformat()
