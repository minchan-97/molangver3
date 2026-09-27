"""organism/worker.py — Supabase 영속화판.

실행 전 pull → 사이클 → 실행 후 push. 로컬 pkl 에 의존하지 않는다.

원본 대비 바뀐 점:
  1. 상태를 Supabase 에서 읽고 쓴다. 러너가 매번 초기화돼도 기억이 남는다.
  2. 배치 스냅샷: 사이클 시작 시점의 novelty / last_topic 을 고정해
     같은 내용이 결과 순서에 따라 다르게 판정되던 문제를 없앴다.
  3. 정체성 프롬프트를 data/molang.pkl 이 아니라 Supabase 에서 읽는다.
     pkl 을 레포에 두면 개인정보가 그대로 노출된다.
  4. 실행 기록을 organism_runs 에 남긴다. 실패해도 흔적이 남는다.
"""
from __future__ import annotations
import argparse
import json
import os
import random
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from organism.curiosity import (choose_topic, brave_search,
                                expand_query_with_openai, infer_topics)
from organism.nm_guard import evaluate
from organism.topology import rebuild
from organism.store import OrganismStore

SOM_PATH = os.environ.get('ORGANISM_SOM', 'data/curiosity_som.pkl')


def ingest_result(state, topic, r, snapshot, new_items):
    """snapshot = {'novelty': float, 'prev_topic': str} — 배치 내 고정값."""
    uid = state.uid(r.get('url', '') + r.get('title', ''))
    if any(x.get('id') == uid for x in state.observations):
        return None

    item = {
        'id': uid, 'topic': topic,
        'title': (r.get('title') or '')[:300],
        'text': (r.get('text') or '')[:2400],
        'url': r.get('url', ''), 'at': time.time(),
    }
    gate = evaluate(state, item,
                    novelty=snapshot['novelty'],
                    prev_topic=snapshot['prev_topic'])
    item.update(gate)

    state.observations.append(item)
    bucket = {'candidate': state.candidates,
              'quarantine': state.quarantine,
              'reject': state.rejected}[gate['status']]
    bucket.append(item)
    new_items.append(item)

    reward = (gate['score'] - .4) if gate['status'] != 'reject' else -.15
    state.touch_interest(topic, reward)

    for tag in infer_topics(item['title'] + ' ' + item['text'], 3):
        if tag != topic:
            state.interests[tag] = max(
                0.0, state.interests.get(tag, 0) * .99 + .03 * max(0, reward))
    return item


def curiosity_cycle(state, store, deep=False):
    prompt = store.identity_prompt()
    topic = choose_topic(state, random.Random(time.time_ns()))
    query = expand_query_with_openai(topic, prompt) if deep else topic

    # 배치 스냅샷 — 이 사이클 내내 같은 값을 쓴다
    snapshot = {'novelty': state.novelty(topic),
                'prev_topic': state.last_topic}

    results = brave_search(query, os.environ.get('BRAVE_API_KEY'),
                           count=int(os.environ.get('CURIOSITY_RESULTS', '5')))

    new_items = []
    for r in results:
        ingest_result(state, topic, r, snapshot, new_items)

    store.record_observations(new_items)

    state.curiosity_history.append({
        'at': time.time(), 'topic': topic, 'query': query, 'deep': deep,
        'found': len(results), 'ingested': len(new_items)})

    return {
        'topic': topic, 'query': query,
        'found': len(results), 'ingested': len(new_items),
        'candidate': sum(x['status'] == 'candidate' for x in new_items),
        'quarantine': sum(x['status'] == 'quarantine' for x in new_items),
        'rejected': sum(x['status'] == 'reject' for x in new_items),
    }


def maintenance(state):
    # 관심 감쇠: 초기의 우연한 한 번이 탐색을 영구 독점하지 않게.
    for k in list(state.interests):
        state.interests[k] *= .997
        if state.interests[k] < .002:
            state.interests.pop(k, None)
    state.cycle += 1
    return rebuild(state, SOM_PATH)


def reflect(state):
    top = sorted(state.interests.items(), key=lambda kv: -kv[1])[:8]
    return {'at': time.time(), 'cycle': state.cycle, 'top_interests': top,
            'candidate': len(state.candidates),
            'quarantine': len(state.quarantine),
            'rejected': len(state.rejected)}


def _where():
    """
    예외가 난 자리. 라이브러리 안쪽(site-packages)은 건너뛰고
    **우리 코드의 마지막 줄**을 찍는다. 'secrets.py:324' 같은 건
    누가 불렀는지 알려주지 않는다.
    """
    import traceback
    tb = traceback.extract_tb(sys.exc_info()[2])
    if not tb:
        return '?'
    ours = [f for f in tb
            if ROOT in os.path.abspath(f.filename)
            and 'site-packages' not in f.filename]
    chain = [f"{os.path.basename(f.filename)}:{f.lineno}({f.name})"
             for f in (ours or tb)[-3:]]
    tail = tb[-1]
    return " → ".join(chain) + f" ⇒ {os.path.basename(tail.filename)}:{tail.lineno}"


def main(mode):
    store = OrganismStore()
    store.start_run(mode)
    out = {'mode': mode, 'run_id': store.run_id}

    try:
        state = store.pull()
        out['resumed'] = {'cycle': state.cycle,
                          'interests': len(state.interests),
                          'observations': len(state.observations)}

        cyc = None
        if mode in ('hourly', 'all'):
            # 조용한 생각은 LLM 을 안 부른다 → 자주 돌려도 비용이 없다.
            # 사람도 늘 생각하지만 그걸 매번 문장으로 만들지는 않는다.
            import musing
            # 깨어난 김에 여러 번 생각한다 (러너 띄우는 값이 2분, 생각은 몇 ms)
            out['musing'] = musing.think_many(
                state, rounds=int(os.environ.get('MUSING_ROUNDS', 30)),
                log=print)
            # 검색은 매번이 아니라 가끔 (기본 3회에 1번)
            every = max(1, int(os.environ.get('SEARCH_EVERY', 3)))
            if state.cycle % every == 0:
                cyc = curiosity_cycle(state, store, deep=False)
                out['curiosity'] = cyc
            else:
                out['curiosity'] = f'이번엔 생각만 (다음 검색까지 {every - (state.cycle % every)}회)'
            out['topology'] = maintenance(state)

        # 호기심이 사고 구조를 바꾸는 자리 — 승인된 근거를 트리에 먹이고,
        # 쌓이면 판단 단계를 늘리고, 안 잡히는 주제가 모이면 새 유형을 만든다.
        try:
            import curiosity_growth
            from tree_registry import TreeRegistry
            import registry_store
            _reg = TreeRegistry()
            registry_store.load_into(store.sb, _reg)
            _gone = _reg.wither()
            if _gone:
                print(f"  안 쓰인 사고유형 정리: {', '.join(_gone)}")
            out['withered'] = _gone
            out['growth'] = curiosity_growth.run(
                store.sb, _reg, state=state,
                api_key=os.environ.get('OPENAI_API_KEY'), log=print)
            if out['growth'].get('deepened') or out['growth'].get('new_type') \
                    or out['growth'].get('memory', {}).get('fed'):
                registry_store.save(store.sb, _reg)
        except Exception as e:
            out['growth'] = {'error': str(e)[:200],
                             'where': _where(), 'type': type(e).__name__}

        # 먼저 말 걸기 — 계기가 있을 때만 (없으면 아무 말도 안 한다)
        try:
            import outbox
            from molang_store import SupabaseIdentity
            _ident = SupabaseIdentity(store.sb)
            _msg = outbox.make(store.sb, identity=_ident, registry=_reg,
                               api_key=os.environ.get('OPENAI_API_KEY'))
            out['nudge'] = _msg or '계기 없음'
        except Exception as e:
            out['nudge'] = {'error': str(e)[:200],
                            'where': _where(), 'type': type(e).__name__}

        if mode in ('nightly', 'all'):
            cyc = curiosity_cycle(state, store, deep=True)
            out['deep_curiosity'] = cyc
            out['topology_night'] = maintenance(state)
            entry = reflect(state)
            try:            # 조용한 생각의 흔적을 회고 재료로
                import musing
                entry['musing_context'] = musing.to_reflection_context(state)
            except Exception:
                pass
            store.record_reflection(entry)
            out['reflection'] = entry

        store.push_state(state, mode)
        som_meta = out.get('topology_night') or out.get('topology') or {}
        if som_meta.get('trained'):
            store.push_som(SOM_PATH, som_meta)

        store.finish_run(
            topic=(cyc or {}).get('topic'),
            query=(cyc or {}).get('query'),
            found=(cyc or {}).get('found'),
            ingested=(cyc or {}).get('ingested'),
            candidate=(cyc or {}).get('candidate'),
            quarantine=(cyc or {}).get('quarantine'),
            rejected=(cyc or {}).get('rejected'),
            som=som_meta or None,
        )

    except Exception as e:
        out['error'] = str(e)
        traceback.print_exc()
        try:
            store.finish_run(error=str(e)[:2000])
        except Exception:
            pass
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        raise

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['hourly', 'nightly', 'all'],
                    default='hourly')
    main(ap.parse_args().mode)
