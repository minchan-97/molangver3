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
    # 승인된 하위 목적이 주제 고르기와 검색어에 실린다
    try:
        import purpose_drive
        subs = purpose_drive.load(store.sb)
    except Exception:
        subs = []
    topic = choose_topic(state, random.Random(time.time_ns()), subs=subs)
    pctx = ""
    try:
        pctx = purpose_drive.query_context(subs, topic) if subs else ""
    except Exception:
        pass
    query = (expand_query_with_openai(topic, prompt, purpose_ctx=pctx)
             if deep else topic)

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
            try:        # 문득 옛일을 떠올리고, 그게 탐색 주제가 되게
                from molang_store import SupabaseIdentity
                from organism.curiosity import nudge_from_memory
                _id = SupabaseIdentity(store.sb)
                # 지금 어디에 있고 무엇을 봤는지가 계기가 된다.
                # **여행 중이면 섬의 그곳이 계기여야 한다** — 섬에 있는데
                # 집 부엌이 기억을 부르면 앞뒤가 안 맞는다.
                try:
                    import reminisce as _rm, travel as _tvr
                    _cur = (_tvr.load(store.sb) or {}).get('current')
                    if _cur:
                        import island as _isr
                        _room = _cur.get('spot') or ''
                        _seen = (_cur.get('seen') or [{}])[-1]
                        _cue = _rm.cue_from(
                            place=_room,
                            room_words=_isr.SPOTS.get(_room, []),
                            said=_seen.get('scene', ''),
                            topic=(state.last_topic or ''))
                    else:
                        import home as _hm
                        _hh = _hm.load(store.sb)
                        _room = (_hh.get('where') or {}).get('molang') or ''
                        _cue = _rm.cue_from(
                            place=_room, room_words=_hm.ROOMS.get(_room, []),
                            topic=(state.last_topic or ''))
                except Exception:
                    _room, _cue = '', set()
                _rem = nudge_from_memory(state, list(_id.learned_facts), cue=_cue)
                if isinstance(_rem, dict):       # 계기로 떠오른 경우
                    print(f"  {_room}에서 떠오름 → 관심: "
                          f"{', '.join(_rem['words'])}"
                          + (f"  ({_rem['from'][0]}…)" if _rem.get('from') else ''))
                    out['reminisce'] = {**_rem, 'place': _room}
                elif _rem:
                    print(f"  문득 떠오름 → 관심: {', '.join(_rem)}")
                    out['reminisce'] = _rem
                else:
                    out['reminisce'] = []
            except Exception as e:
                out['reminisce'] = {'error': str(e)[:100]}
            out['musing'] = musing.think_many(
                state, rounds=int(os.environ.get('MUSING_ROUNDS', 30)),
                log=print)
            # 검색은 매번이 아니라 가끔 (기본 3회에 1번)
            every = max(1, int(os.environ.get('SEARCH_EVERY', 3)))
            if state.cycle % every == 0:
                cyc = curiosity_cycle(state, store, deep=False)
                out['curiosity'] = cyc
                # 여행 — **시간당에도 움직인다.** 밤에만 옮기면 하루 한 곳이라
                # 여행이 아니라 잠자고 일어나면 순간이동하는 꼴이 된다.
                try:
                    import travel as _tv
                    from molang_store import SupabaseIdentity as _SI2
                    _t = _tv.load(store.sb)
                    _tv.stir_longing(_t, state.interests)
                    _piu_id = None
                    try:
                        import piupiu as _pp
                        _piu_id = _pp.identity(store.sb)
                    except Exception:
                        pass
                    _mood_now = ((state.moods or [{}])[-1]
                                 if getattr(state, 'moods', None) else {})
                    if _t.get('current'):
                        import island as _is
                        out['travel'] = _is.day(
                            store.sb, _t, state, _SI2(store.sb), _piu_id,
                            api_key=os.environ.get('OPENAI_API_KEY'))
                    elif mode in ('nightly', 'all'):
                        # 떠나는 것은 밤에만 (짐을 싸고 공항까지 가야 하니까)
                        out['travel'] = _tv.go(store.sb, _t, state,
                                               _SI2(store.sb), _piu_id, _mood_now)
                    _tv.save(store.sb, _t)
                except Exception as e:
                    out['travel'] = {'error': str(e)[:120]}
                # 집에서 한 회차 — 다만 여행 중이면 집에 없다
                try:
                    import home as _home, travel as _tvchk
                    if (_tvchk.load(store.sb) or {}).get('current'):
                        out['home'] = {'skip': '여행 중'}
                    else:
                        out['home'] = _home.tick(store.sb, state)
                except Exception as e:
                    out['home'] = {'error': str(e)[:120]}

                # 바깥 — 관심이 한쪽으로 쌓이면 지형이 생기고, 심심하면 나간다.
                # 집과 달리 지형은 재배열되지 않는다. 그게 '바깥'이라는 뜻이다.
                try:
                    import land as _land
                    _ld = _land.load(store.sb)
                    _born = _land.maybe_grow(_ld, state.interests)
                    _last_mood = (state.moods or [{}])[-1] if getattr(
                        state, 'moods', None) else {}
                    _went = _land.maybe_go(_ld, state, _last_mood)
                    _land.save(store.sb, _ld)
                    if _went:
                        state.outings = (getattr(state, 'outings', []) or [])[-40:] + [{
                            'at': time.time(), 'kind': _went['place']['kind'],
                            'first': _went['first']}]
                    out['land'] = {'born': _born and _born['kind'],
                                   'went': _went and _went['place']['kind'],
                                   'first': bool(_went and _went['first']),
                                   'places': [p['kind'] for p in _ld['places']],
                                   'stim': _land.stim_to_mood(_went)}
                except Exception as e:
                    out['land'] = {'error': str(e)[:120]}

                # 피우피우 — 함께 사는 노란 병아리.
                # 검색이 도는 회차에만 같이 움직인다: 매 회차면 비용이 세 배,
                # 밤에 한 번이면 둘이 같이 산다는 느낌이 안 난다. 하루 여덟 번쯤.
                try:
                    import piupiu
                    from molang_store import SupabaseIdentity
                    from organism.curiosity import brave_search
                    _rng = random.Random(time.time_ns())
                    _ptopic = piupiu.pick_topic(state, _rng)
                    _res = brave_search(_ptopic, os.environ.get('BRAVE_API_KEY'),
                                        count=3)
                    _seen = None
                    if _res:
                        r0 = _res[0]
                        _seen = {'topic': _ptopic, 'title': r0.get('title'),
                                 'text': r0.get('text') or r0.get('description'),
                                 'url': r0.get('url')}
                        # 1) 피우피우가 찾아온 것도 몰랑이 검토함으로
                        ingest_result(state, _ptopic, r0,
                                      {'novelty': state.novelty(_ptopic),
                                       'prev_topic': state.last_topic}, _pitems := [])
                        store.record_observations(_pitems)
                    _piu = piupiu.identity(store.sb)
                    _mol = SupabaseIdentity(store.sb)
                    _where = (out.get('home') or {})
                    _mol.place = _where.get('molang')
                    _piu.place = _where.get('piupiu')
                    _talk = piupiu.converse(
                        store.sb, _mol, _piu, _seen,
                        os.environ.get('OPENAI_API_KEY'),
                        place=_where.get('molang'),
                        same_room=bool(_where.get('same_room')),
                        state=state)
                    # 2) 관심이 서로 물든다
                    _bleed = piupiu.bleed_interests(state, {_ptopic: 1.0})
                    out['piupiu'] = {'topic': _ptopic, 'bleed': _bleed,
                                     **({'talked': True} if _talk.get('talk') else _talk)}
                except Exception as e:
                    out['piupiu'] = {'error': str(e)[:150]}

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
            _loaded = registry_store.load_into(store.sb, _reg)
            if _loaded == 0:
                print("  ⚠️ 사고 트리를 하나도 못 불러왔습니다 "
                      "(molang_registry 확인 필요)")
            # 복원이 크게 줄었으면 **저장하지 않는다.**
            # 덜 불러온 상태로 저장하면 그게 덮어써져서 영영 잃는다.
            _prev = int(getattr(state, 'tree_count', 0) or 0)
            _safe_to_save = True
            if _prev and len(_reg.trees) < _prev * 0.8:
                print(f"  ⚠️ 사고 유형이 {_prev} → {len(_reg.trees)} 로 줄었습니다. "
                      "이번 회차는 저장하지 않습니다 (덮어쓰기 방지)")
                _safe_to_save = False
            else:
                state.tree_count = len(_reg.trees)
            _gone = _reg.wither()
            if _gone:
                print(f"  안 쓰인 사고유형 정리: {', '.join(_gone)}")
            out['withered'] = _gone
            try:
                import purpose_drive as _pd
                _subs_now = _pd.load(store.sb)
            except Exception:
                _subs_now = []
            out['growth'] = curiosity_growth.run(
                store.sb, _reg, state=state,
                api_key=os.environ.get('OPENAI_API_KEY'), log=print)
            if out['growth'].get('deepened') or out['growth'].get('new_type') \
                    or out['growth'].get('memory', {}).get('fed'):
                _rs = (registry_store.save(store.sb, _reg) if _safe_to_save
                       else {"ok": True, "skipped": "복원이 불완전해 저장 보류"})
                if not _rs.get("ok"):
                    print(f"  ⚠️ 트리 저장 실패: {_rs.get('error')}")
        except Exception as e:
            out['growth'] = {'error': str(e)[:200],
                             'where': _where(), 'type': type(e).__name__}

        try:    # 이번 회차에 소화한 양 (충동을 빼는 신호)
            state.last_fed = int((out.get('growth') or {})
                                 .get('memory', {}).get('fed', 0) or 0)
        except Exception:
            state.last_fed = 0

        # 기분 — 네 축. 판단을 대신하지 않고 가중치로만 작용한다.
        try:
            import mood as _mood
            from molang_store import SupabaseIdentity as _SI
            _cur = out.get('curiosity')
            _rem = out.get('reminisce')
            _ev = {
                "new": int(_cur.get('ingested', 0)) if isinstance(_cur, dict) else 0,
                "settled": int((out.get('growth') or {})
                               .get('memory', {}).get('fed', 0) or 0),
                "repeat": len(_rem) if isinstance(_rem, list) else 0,
            }
            _texts = []
            try:
                _texts = [f"{o.get('topic','')} {o.get('title','')}"
                          for o in (state.observations or [])[-5:]]
            except Exception:
                pass
            state.last_qe = float((out.get('topology') or
                                   out.get('topology_night') or {}).get('mean_qe', 0) or 0)
            out['mood'] = _mood.feel(store.sb, _SI(store.sb), state,
                                     events=_ev, texts=_texts)
            out['mood_bias'] = _mood.bias(out['mood'])
        except Exception as e:
            out['mood'] = {'error': str(e)[:120]}

        # 목적이 아래에서부터 자란다 — 조건이 찼을 때만 제안, 승인은 사람이
        try:
            import purpose_growth, purpose as _p
            _core = ''
            try:
                _core = (store.identity_prompt() or '').split(
                    '[무엇을 향해 사는가]')[-1].split('\n')[0].strip()
            except Exception:
                _core = _p.PURPOSE
            _sub = purpose_growth.propose_sub(
                store.sb, state, os.environ.get('OPENAI_API_KEY'), _core)
            _cor = purpose_growth.propose_core(
                store.sb, os.environ.get('OPENAI_API_KEY'), _core)
            out['purpose'] = {'sub': _sub, 'core': _cor}
        except Exception as e:
            out['purpose'] = {'error': str(e)[:150]}

        # 먼저 말 걸기 — 계기가 있을 때만 (없으면 아무 말도 안 한다)
        try:
            import outbox
            from molang_store import SupabaseIdentity
            _ident = SupabaseIdentity(store.sb)
            _msg = outbox.make(store.sb, identity=_ident, registry=_reg,
                               api_key=os.environ.get('OPENAI_API_KEY'),
                               state=state)
            out['nudge'] = _msg or '계기 없음'

            # 하고 싶은 말이 앱 밖으로도 닿게.
            # 앱을 안 열면 이 아이 말이 아무 데도 안 간다.
            try:
                import notify as _nt
                if _nt.available():
                    out['notify'] = _nt.push_pending(
                        store.sb, app_url=os.environ.get('APP_URL', ''))
            except Exception as _ne:
                out['notify'] = {'error': str(_ne)[:80]}
        except Exception as e:
            out['nudge'] = {'error': str(e)[:200],
                            'where': _where(), 'type': type(e).__name__}

        if mode in ('nightly', 'all'):
            try:    # 기억을 목록이 아니라 지도로 — 밤에 한 번 다시 그린다
                import semantic_map as _smap
                out['map'] = _smap.rebuild(store.sb)
            except Exception as e:
                out['map'] = {'error': str(e)[:120]}

            try:    # 확신은 굳기만 하지 않는다 — 묵은 것은 옅어진다
                import belief_decay as _bd
                out['fade'] = _bd.sweep(store.sb)
            except Exception as e:
                out['fade'] = {'error': str(e)[:100]}

            try:        # 낮에 못 다룬 것이 겹쳐 꿈이 된다 (사실이 되지는 않는다)
                import dream as _dream
                from molang_store import SupabaseIdentity
                out['dream'] = _dream.dream(
                    store.sb, SupabaseIdentity(store.sb), state,
                    os.environ.get('OPENAI_API_KEY'))
            except Exception as e:
                out['dream'] = {'error': str(e)[:150]}

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
