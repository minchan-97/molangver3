"""
growth_export.py — 성장 기록을 한 파일(.pkl)로 내려받는다.

왜 화면이 아니라 파일인가
  화면은 '지금 어떤가'를 보여주지만, 성장은 '어떻게 변해왔나'다.
  나중에 파이썬으로 열어 그래프를 그리거나, 조건을 바꾼 실험과 나란히
  비교하려면 원본이 통째로 있어야 한다.
  (continuity 를 끄고 돌린 것과 비교하려면 두 파일이 필요하다)

담기는 것
  trees        사고 트리 전부 — 노드·전이 확률·기억·경로 이력
  creation_log 유형이 언제 무엇 때문에 생겼는지
  interests    관심사와 방문 횟수
  observations 무엇을 찾아봤고 어떻게 판정됐는지
  musings      조용한 생각의 흔적 (말이 되기 전의 생각)
  reflections  밤마다 쓴 회고
  outbox       먼저 말 건 기록 (규칙 + 문장)
  facts        확신·미확신 사실
  meta         내보낸 시각, 회차, 집계

여는 법
    import pickle
    d = pickle.load(open('molang_growth.pkl','rb'))
    d['meta'], d['interests'], len(d['trees'])
"""
from __future__ import annotations
import pickle
import time


def _rows(sb, table, cols="*", order="id", limit=2000, desc=True):
    try:
        q = sb.table(table).select(cols).order(order, desc=desc).limit(limit)
        return q.execute().data or []
    except Exception as e:
        return [{"_error": str(e)[:120]}]


def collect(sb, registry=None, state=None, identity=None) -> dict:
    """지금 서버와 메모리에 있는 성장 기록을 모은다."""
    out = {"meta": {"at": time.time(),
                    "at_str": time.strftime("%Y-%m-%d %H:%M:%S")}}

    # 1) 사고 트리 — 판단 구조 그 자체
    trees = {}
    if registry is not None:
        try:
            from tree_registry import TreeRegistry
            for tid, t in (registry.trees or {}).items():
                blob = TreeRegistry._tree_blob(t)
                blob["memory_n"] = len(getattr(t, "memory", []))
                blob["history_n"] = len(getattr(t, "history", []))
                blob["grown_nodes"] = [n for n in t.nodes
                                       if str(n).startswith("grown_")]
                trees[tid] = blob
        except Exception as e:
            trees = {"_error": str(e)[:120]}
        out["creation_log"] = list(getattr(registry, "creation_log", []) or [])
        out["usage_count"] = dict(getattr(registry, "usage_count", {}) or {})
    out["trees"] = trees

    # 2) 관심 지형과 생각의 흔적
    if state is not None:
        out["interests"] = dict(getattr(state, "interests", {}) or {})
        out["visited"] = dict(getattr(state, "visited", {}) or {})
        out["musings"] = list(getattr(state, "musings", []) or [])
        out["cycle"] = getattr(state, "cycle", None)

    # 3) 집·바깥·기분·꿈 — 이것들이 빠지면 pkl 로는 작동 여부를 볼 수 없다
    if state is not None:
        out["moods"] = list(getattr(state, "moods", []) or [])
        out["dreams_state"] = list(getattr(state, "dreams", []) or [])
        out["outings"] = list(getattr(state, "outings", []) or [])
        out["reminisced"] = list(getattr(state, "reminisced", []) or [])
        out["drive"] = float(getattr(state, "drive", 0.0) or 0.0)
    if sb is not None:
        try:
            import home as _home
            out["home"] = _home.load(sb)
            out["home_coords"] = {k: list(v) for k, v in
                                  _home.layout()["coords"].items()}
        except Exception as e:
            out["home"] = {"_error": str(e)[:80]}
        try:
            import land as _land
            out["land"] = _land.load(sb)
        except Exception as e:
            out["land"] = {"_error": str(e)[:80]}
        out["dreams"] = _rows(sb, "molang_dreams", limit=100)
        out["peer_talks"] = _rows(sb, "molang_peer_talks", limit=100)
        out["purposes"] = _rows(sb, "molang_purposes", limit=50)

    # 4) 서버 기록
    if sb is not None:
        out["observations"] = _rows(
            sb, "organism_observations",
            "id,topic,title,url,status,score,source_trust,novelty,seen_at")
        out["reflections"] = _rows(sb, "organism_reflections")
        out["outbox"] = _rows(sb, "molang_outbox", "id,body,rule,created_at,sent_at")
        out["quarantine"] = _rows(sb, "molang_quarantine")
        out["runs"] = _rows(sb, "organism_runs", limit=300)

    # 5) 사실
    if identity is not None:
        try:
            out["facts"] = [dict(f) for f in identity.learned_facts]
            out["persona"] = identity.persona
        except Exception:
            pass

    # 6) 한눈에 보는 집계
    tr = out.get("trees") or {}
    out["meta"].update({
        "tree_count": len(tr) if isinstance(tr, dict) else 0,
        "grown_nodes": sum(len(v.get("grown_nodes", []))
                           for v in tr.values() if isinstance(v, dict)),
        "tree_memory": sum(v.get("memory_n", 0)
                           for v in tr.values() if isinstance(v, dict)),
        "interests": len(out.get("interests") or {}),
        "observations": len(out.get("observations") or []),
        "musings": len(out.get("musings") or []),
        "facts": len(out.get("facts") or []),
        "cycle": out.get("cycle"),
        "moods": len(out.get("moods") or []),
        "dreams": len(out.get("dreams") or []),
        "outings": len(out.get("outings") or []),
        "places": len(((out.get("land") or {}).get("places")) or []),
        "objects": sum(len(v) for v in
                       ((out.get("home") or {}).get("objects") or {}).values()),
        "drive": out.get("drive"),
        "purposes": len(out.get("purposes") or []),
        "peer_talks": len(out.get("peer_talks") or []),
    })
    return out


def to_bytes(sb, registry=None, state=None, identity=None) -> bytes:
    return pickle.dumps(collect(sb, registry, state, identity))


def summary_line(data: dict) -> str:
    m = data.get("meta", {})
    return (f"사고유형 {m.get('tree_count')}개 · 늘린 단계 {m.get('grown_nodes')}개 · "
            f"사고기억 {m.get('tree_memory')}개 · 관심사 {m.get('interests')}개 · "
            f"관측 {m.get('observations')}건 · 꿈 {m.get('dreams')}개 · "
            f"지형 {m.get('places')}곳 · 물건 {m.get('objects')}개 · "
            f"목적 {m.get('purposes')}개")
