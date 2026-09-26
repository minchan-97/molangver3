"""
organism/store.py — 유기체 상태의 Supabase 영속화.

기존 구조의 문제:
  GitHub Actions 러너는 매 실행마다 새 파일시스템이고, .gitignore 가
  *.pkl 을 제외한다. 따라서 data/organism_state.pkl 은 체크아웃에
  존재하지 않고, 워커는 매번 빈 OrganismState() 로 시작했다.
  cycle 은 영원히 1, interests 는 영원히 비어 있고, novelty 는 항상 1.0.

해결:
  실행 전 pull(), 실행 후 push(). 상태 갱신은 version CAS 로 원자화.
  관측은 blob 이 아니라 행으로 올라가므로 나중에 쿼리할 수 있다.
"""
from __future__ import annotations
import os
import time
import uuid
from datetime import datetime, timezone

from organism.state import OrganismState

OBS_HYDRATE = 1200   # 토폴로지 재구성에 필요한 최근 관측 수


def _client():
    from supabase import create_client
    url = os.environ.get('SUPABASE_URL')
    key = os.environ.get('SUPABASE_SERVICE_KEY')
    if not url or not key:
        raise RuntimeError(
            'SUPABASE_URL / SUPABASE_SERVICE_KEY 가 필요합니다. '
            '이게 없으면 워커는 매 실행마다 기억을 잃습니다.')
    return create_client(url, key)


class OrganismStore:
    def __init__(self, client=None):
        self.sb = client or _client()
        self.run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        self._version = None

    # ---------- 실행 전 ----------

    def pull(self) -> OrganismState:
        row = self.sb.table('organism_state').select('*').eq('id', 1) \
                  .single().execute().data
        self._version = row['version']

        s = OrganismState()
        s.cycle = row.get('cycle') or 0
        s.interests = {k: float(v) for k, v in (row.get('interests') or {}).items()}
        s.visited = {k: int(v) for k, v in (row.get('visited') or {}).items()}
        s.transition_counts = {k: int(v) for k, v
                               in (row.get('transition_counts') or {}).items()}
        s.last_topic = row.get('last_topic') or ''
        s.musings = row.get('musings') or []

        obs = self.sb.table('organism_observations') \
            .select('uid,topic,title,text,url,status,score,source_trust,'
                    'transition_p,novelty,seen_at') \
            .order('seen_at', desc=True).limit(OBS_HYDRATE).execute().data or []

        for o in reversed(obs):
            item = {
                'id': o['uid'], 'topic': o['topic'],
                'title': o.get('title') or '', 'text': o.get('text') or '',
                'url': o.get('url') or '', 'status': o['status'],
                'score': o.get('score'), 'source_trust': o.get('source_trust'),
                'transition_p': o.get('transition_p'), 'novelty': o.get('novelty'),
                'at': time.time(),
            }
            s.observations.append(item)
            bucket = {'candidate': s.candidates,
                      'quarantine': s.quarantine,
                      'reject': s.rejected}[o['status']]
            bucket.append(item)

        return s

    # ---------- 실행 중 ----------

    def record_observations(self, items: list[dict]):
        """새 관측만 올린다. uid unique 라 중복은 조용히 건너뛴다."""
        if not items:
            return 0
        rows = [{
            'uid': i['id'], 'topic': i['topic'],
            'title': (i.get('title') or '')[:300],
            'text': (i.get('text') or '')[:2400],
            'url': i.get('url') or '',
            'status': i['status'], 'score': i.get('score'),
            'source_trust': i.get('source_trust'),
            'transition_p': i.get('transition_p'),
            'novelty': i.get('novelty'),
            'run_id': self.run_id,
        } for i in items]
        try:
            res = self.sb.table('organism_observations') \
                .upsert(rows, on_conflict='uid', ignore_duplicates=True) \
                .execute()
            return len(res.data or [])
        except Exception as e:
            print('observation upsert warning:', e)
            return 0

    # ---------- 실행 후 ----------

    def push_state(self, s: OrganismState, mode: str):
        """version CAS. 시간당/야간 워커가 겹쳐도 한쪽만 이긴다."""
        # musings(조용한 생각의 흔적)는 RPC 목록에 없어서 매번 사라졌다.
        # CAS 뒤에 따로 올린다. 실패해도 본 상태 저장은 막지 않는다.
        try:
            if getattr(s, 'musings', None):
                self.sb.table('organism_state').update(
                    {'musings': s.musings[-200:]}).eq('id', 1).execute()
        except Exception as e:
            print('musings 저장 건너뜀:', str(e)[:80])
        self.sb.rpc('organism_commit_state', {
            'p_version': self._version,
            'p_cycle': s.cycle,
            'p_interests': {k: round(float(v), 6) for k, v in s.interests.items()},
            'p_visited': s.visited,
            'p_transition_counts': s.transition_counts,
            'p_last_topic': s.last_topic,
            'p_mode': mode,
        }).execute()

    def push_som(self, path: str, meta: dict):
        if not os.path.exists(path):
            return
        blob = open(path, 'rb').read()
        self.sb.table('organism_som').upsert({
            'id': 1, 'blob': blob.hex(),
            'n_items': meta.get('n'), 'occupied': meta.get('occupied'),
            'mean_qe': meta.get('mean_qe'),
            'updated_at': _now(),
        }).execute()

    def start_run(self, mode: str):
        self.sb.table('organism_runs').insert({
            'run_id': self.run_id, 'mode': mode}).execute()

    def finish_run(self, **fields):
        fields['ended_at'] = _now()
        self.sb.table('organism_runs').update(fields) \
            .eq('run_id', self.run_id).execute()

    def record_reflection(self, entry: dict):
        self.sb.table('organism_reflections').insert({
            'cycle': entry.get('cycle'),
            'top_interests': entry.get('top_interests'),
            'counts': {k: entry.get(k) for k in
                       ('candidate', 'quarantine', 'rejected')},
        }).execute()

    # ---------- 정체성 프롬프트 ----------

    def identity_prompt(self) -> str:
        """
        molang.pkl 을 저장소에 두지 않는다.
        pkl 에는 병원·여자친구·근무지 같은 개인정보가 들어 있고,
        레포에 올리면 그대로 노출된다. Supabase 에서 읽어온다.
        """
        try:
            idn = self.sb.table('molang_identity').select('persona,values,rules') \
                      .eq('id', 1).maybe_single().execute().data or {}
            facts = self.sb.table('molang_facts_active') \
                .select('text').order('strength', desc=True) \
                .limit(20).execute().data or []
        except Exception:
            return ''

        parts = []
        if idn.get('persona'):
            parts.append(idn['persona'])
        if idn.get('values'):
            parts.append('가치관: ' + ', '.join(idn['values']))
        if facts:
            parts.append('알고 있는 것: ' +
                         ' / '.join(f['text'] for f in facts))
        return '\n'.join(parts)


def _now():
    return datetime.now(timezone.utc).isoformat()
