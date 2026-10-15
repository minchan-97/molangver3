"""
semantic_map_v.py — **벡터로 그린 의미 지도.** 기존 지도와 나란히 둔다.

지금 지도가 막히는 자리
  semantic_map 은 **함께 나온 횟수**만으로 실을 잇는다. 그래서
  한 자료에만 나온 낱말은 영영 이어지지 않는다.
  `토끼`·`우주`·`생물` 이 몇 주째 자리를 못 잡는 이유가 이것이다.
  (그리고 토끼는 몰랑이 자신인데도 그렇다)

  더 나아가, '바다' 와 '파도' 가 같은 글에 없었으면 **둘이 가깝다는
  것을 알 길이 없다.** 겪은 것만으로는 닿지 못하는 관계가 있다.

무엇이 달라지나
  낱말마다 **좌표**가 있다. 함께 나온 적이 없어도 뜻이 가까우면
  가깝다. 그러니 처음 보는 낱말도 **들어오자마자 자리를 가진다.**

  다만 겪은 것을 버리지 않는다. 실의 굵기는 둘을 곱해서 정한다.
    함께 나옴  × 뜻이 가까움
  겪어서 아는 것과 말의 뜻이 **섞이는 게 아니라 겹친다.**

왜 나란히 두나
  기존 지도를 덮어쓰면 갈래가 통째로 재편되고, 되돌릴 수도 없다.
  그래서 따로 그려 **견줘본 뒤에** 쓴다.
  (연속성 지표 자체는 사실의 확신을 보므로 흔들리지 않지만,
   꺼내는 것이 달라지면 같은 질문에 다른 답이 나온다)
"""
from __future__ import annotations
import math
import time
from collections import Counter, defaultdict

MIN_LINK = 2              # 함께 나온 횟수가 이보다 적으면 겪은 실로 안 친다
SIM_LINK = 0.45           # 뜻이 이만큼 가까우면 겪지 않아도 잇는다
MAX_NODES = 1200
SIM_NEIGHBORS = 6         # 낱말 하나가 뜻으로 이을 상대 수


def _words(doc: str) -> list:
    try:
        from semantic_map import _words as w
        return w(doc)
    except Exception:
        import re
        return re.findall(r"[가-힣A-Za-z]{2,}", doc or "")


def build(docs: list, keep: int = MAX_NODES, log=None) -> dict:
    """
    자료 묶음 → 벡터 지도.

    실이 두 갈래로 생긴다.
      겪은 실   함께 나온 것 (지금 지도와 같다)
      뜻의 실   함께 나온 적은 없지만 뜻이 가까운 것
    """
    import vectors as V

    co = defaultdict(Counter)
    freq = Counter()
    for d in docs:
        ws = list(dict.fromkeys(_words(d)))[:14]
        for w in ws:
            freq[w] += 1
        for i in range(len(ws)):
            for j in range(i + 1, len(ws)):
                co[ws[i]][ws[j]] += 1
                co[ws[j]][ws[i]] += 1

    n = max(1, len(docs))
    common = {w for w, c in freq.items() if c / n > 0.25}
    words = [w for w in freq if w not in common]
    words.sort(key=lambda w: -freq[w])
    words = words[:keep]
    wset = set(words)

    edges = {}
    kinds = {"겪음": 0, "뜻": 0, "둘다": 0}

    # 1) 겪은 실 — 함께 나온 것
    for a, row in co.items():
        if a in common or a not in wset:
            continue
        for b, c in row.items():
            if b in common or b not in wset or c < MIN_LINK or a >= b:
                continue
            w = c / math.sqrt(freq[a] * freq[b])
            # 뜻이 가까우면 그 실이 더 굵어진다 (겹쳐서 세진다)
            sim = float(V.of(a) @ V.of(b))
            if sim > 0:
                w *= (1.0 + sim)
                kinds["둘다"] += 1
            else:
                kinds["겪음"] += 1
            edges[(a, b)] = round(w, 3)

    # 2) 뜻의 실 — 겪은 적 없어도 뜻이 가까우면
    #
    #    이것이 지금 지도가 못 하던 일이다. 한 자료에만 나온 낱말도
    #    여기서 자리를 얻는다.
    try:
        placed = [w for w in words if V.has(w)]
        for a in placed:
            for b, sim in V.near(a, k=SIM_NEIGHBORS, pool=placed):
                if sim < SIM_LINK:
                    continue
                key = (a, b) if a < b else (b, a)
                if key in edges:
                    continue
                # 겪지 않은 실은 **얇게** 둔다. 안 겪은 것을 겪은 것만큼
                # 믿을 수는 없다.
                edges[key] = round(0.5 * float(sim), 3)
                kinds["뜻"] += 1
    except Exception:
        pass

    nodes = sorted({x for e in edges for x in e}, key=lambda w: -freq[w])
    nodes = nodes[:keep]
    keepset = set(nodes)
    edges = {k: v for k, v in edges.items()
             if k[0] in keepset and k[1] in keepset}

    if log:
        log(f"  벡터 지도: 마디 {len(nodes)} · 실 {len(edges)} "
            f"(겪음 {kinds['겪음']} · 겹침 {kinds['둘다']} · 뜻 {kinds['뜻']})")
    return {"freq": {w: freq[w] for w in nodes}, "edges": edges,
            "nodes": {w: 1 for w in nodes},
            "kinds": kinds, "built_at": time.time(), "docs": len(docs)}


def clusters(gmap: dict, min_size: int = 3) -> list:
    """갈래는 기존 방식 그대로 — 실이 달라졌으니 결과만 달라진다."""
    import semantic_map as SM
    return SM.clusters(gmap, min_size=min_size)


def save(sb, gmap: dict, cls: list) -> bool:
    """**따로** 저장한다. 기존 지도를 건드리지 않는다."""
    try:
        sb.table("molang_map_v").upsert(
            {"id": 1, "graph": gmap, "clusters": cls,
             "updated_at": "now()"}, on_conflict="id").execute()
        return True
    except Exception:
        return False


def load(sb) -> tuple:
    try:
        rows = (sb.table("molang_map_v").select("graph,clusters")
                .eq("id", 1).limit(1).execute().data) or []
        if rows:
            return (rows[0].get("graph") or {}), (rows[0].get("clusters") or [])
    except Exception:
        pass
    return {}, []


# ── 견주기 ────────────────────────────────────────────────
def compare(old_map: dict, old_cls: list,
            new_map: dict, new_cls: list) -> dict:
    """
    두 지도를 나란히 놓고 본다. **바꿀지 말지는 이 숫자를 보고 정한다.**

    가장 또렷한 시험은 '자리를 못 잡던 낱말이 잡혔는가' 다.
    """
    def unsettled(cls, gmap):
        got = set()
        for c in cls:
            got |= set(c.get("members") or [])
        return [w for w in (gmap.get("freq") or {}) if w not in got]

    def conf(cls):
        v = [c.get("confidence") or 0 for c in cls]
        return round(sum(v) / len(v), 3) if v else 0.0

    uo, un = unsettled(old_cls, old_map), unsettled(new_cls, new_map)
    return {
        "마디": [len(old_map.get("freq") or {}), len(new_map.get("freq") or {})],
        "실": [len(old_map.get("edges") or {}), len(new_map.get("edges") or {})],
        "갈래": [len(old_cls), len(new_cls)],
        "갈래확신": [conf(old_cls), conf(new_cls)],
        "자리못잡음": [len(uo), len(un)],
        "새로잡힌것": sorted(set(uo) - set(un))[:12],
        "새로놓친것": sorted(set(un) - set(uo))[:12],
    }


def rebuild(sb, limit: int = 800, log=print) -> dict:
    """
    기존 지도와 **같은 자료**로 벡터 지도를 그린다.
    같은 자료여야 견주는 뜻이 있다.
    """
    docs = []
    try:
        rows = (sb.table("organism_observations")
                .select("topic,title,text").order("id", desc=True)
                .limit(limit).execute().data) or []
        docs += [f"{r.get('topic','')} {r.get('title') or ''} "
                 f"{(r.get('text') or '')[:200]}" for r in rows]
    except Exception:
        pass
    try:
        rows = (sb.table("molang_facts_active").select("text")
                .limit(400).execute().data) or []
        docs += [r.get("text", "") for r in rows]
    except Exception:
        pass
    docs = [d for d in docs if d and d.strip()]
    if len(docs) < 20:
        return {"skip": f"자료가 {len(docs)}건뿐"}

    gmap = build(docs, log=log)
    cls = clusters(gmap)
    save(sb, gmap, cls)

    # 기존 지도와 견준다 — 바꿀지 말지는 이 숫자를 보고 정한다
    out = {"nodes": len(gmap.get("freq") or {}),
           "edges": len(gmap.get("edges") or {}),
           "clusters": len(cls), "kinds": gmap.get("kinds")}
    try:
        import semantic_map as SM
        og, oc = SM.load(sb)
        if og:
            out["vs"] = compare(og, oc, gmap, cls)
    except Exception:
        pass
    return out
