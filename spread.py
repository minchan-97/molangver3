"""
spread.py — **지도를 타고 번져서 꺼낸다.**

왜 필요했나
  "어디 살아?" 라고 물었는데 "사용자는 부산 일광에 살고 있다" 가
  안 올라왔다. 확신 1.0 짜리인데도. 질문과 겹치는 낱말이 '살' 뿐이라
  점수가 낮았기 때문이다.

  지금 꺼내기는 **표면 일치**에 기대고 있다. 낱말이 겹치거나
  해시 임베딩이 비슷하면 가깝다고 본다. 그런데 해시는 뜻을 모른다.
  '살다' 와 '일광' 이 가깝다는 것은 **글자로는 알 수 없다.**

  그런데 그 관계는 이미 다른 데 있다. 몇 달에 걸쳐 쌓인
  **의미 지도**(마디 755, 갈래 83)와 **낱말 중력**이다.
  꺼낼 때 그걸 안 보고 있었다.

무엇을 하나
  질문의 낱말에서 시작해 지도를 **두 걸음** 번진다.
    1걸음  이어진 마디들 (semantic_map.neighbors)
    2걸음  그 마디가 끌리는 쪽 (word_gravity.attracted)
    그리고 같은 **갈래**에 든 낱말들

  걸음마다 힘이 줄어든다. 멀수록 약하게 치는 것이 자연스럽다.
  그렇게 얻은 '번진 낱말' 이 든 사실을 끌어올린다.

무엇을 하지 않나
  기존 점수를 **갈아치우지 않는다.** 낱말 겹침·확신·새로움은 그대로 두고,
  거기에 번짐을 곱한다. 지도가 성글 때 오히려 나빠지는 걸 막기 위해서다.
"""
from __future__ import annotations
import re

HOP1 = 1.0               # 바로 이어진 것
HOP2 = 0.45              # 한 다리 건넌 것
SAME_CLUSTER = 0.6       # 같은 갈래에 든 것
MAX_SEEDS = 5            # 질문에서 몇 낱말로 시작할까
MAX_SPREAD = 60          # 번진 낱말 상한 (너무 퍼지면 아무거나 걸린다)
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")

_STOP = {"어디", "뭐야", "무엇", "어떻게", "언제", "누구", "그래",
         "지금", "요즘", "오늘", "내가", "너는", "우리", "그거"}


# 말끝이 바뀌어도 같은 말이다. '살아' 와 '살다' 가 지도에서 따로 놀면
# "어디 살아?" 로는 '살다' 에 닿지 못한다.
_TAIL = re.compile(r"(아|어|지|니|나|고|며|면|자|라|요|야|데|대|죠|군)$")


def _stems(w: str) -> list:
    """이 낱말이 지도에서 가질 법한 꼴들."""
    out = [w]
    try:
        from organism.curiosity import strip_josa
        s = strip_josa(w)
        if s and s != w:
            out.append(s)
    except Exception:
        pass
    for base in list(out):
        if len(base) >= 2:
            cut = _TAIL.sub("", base)
            if cut and cut != base:
                # 한 글자여도 '다' 를 붙이면 말이 된다 (살아 → 살 → 살다)
                if len(cut) >= 2:
                    out.append(cut)
                out.append(cut + "다")
                out.append(cut + "기")       # 살 → 살기
    return list(dict.fromkeys(out))


def seeds(question: str, gmap: dict = None) -> list:
    """
    질문에서 시작할 낱말들.
    **지도에 있는 꼴로 바꿔서** 돌려준다 — 안 그러면 닿지 못한다.
    """
    nodes = set((gmap or {}).get("nodes") or {})
    out = []
    for w in TOKEN.findall(question or ""):
        if w in _STOP or len(w) < 2:
            continue
        for cand in _stems(w):
            if nodes and cand not in nodes:
                continue
            if cand not in out:
                out.append(cand)
            break
        else:
            # 지도에 없는 꼴이면, **뜻이 가장 가까운 지도 낱말**로 바꾼다.
            # ('지내' 가 지도에 없어도 '살다' 로 닿을 수 있게)
            placed = False
            if nodes:
                try:
                    import vectors as _vc
                    near = _vc.near(w, k=1, pool=list(nodes))
                    if near and near[0][0] not in out:
                        out.append(near[0][0])
                        placed = True
                except Exception:
                    pass
            if not placed and not nodes and w not in out:
                out.append(w)
    return out[:MAX_SEEDS]


def spread(gmap: dict, question: str, mass: dict = None,
           clusters: list = None) -> dict:
    """
    질문에서 지도를 타고 번진다. {낱말: 세기}.

    세기는 **걸음 수에 따라 줄어든다.** 바로 이어진 것이 가장 세고,
    한 다리 건넌 것과 같은 갈래에 든 것이 그다음이다.
    """
    if not gmap:
        return {}
    try:
        import semantic_map as SM
    except Exception:
        return {}

    out = {}
    starts = seeds(question, gmap)
    for s in starts:
        out[s] = max(out.get(s, 0.0), 1.2)      # 질문에 직접 나온 말

    # 0걸음 — **뜻이 가까운 낱말** (word2vec)
    #
    # 지도는 '함께 나온 적이 있나' 만 안다. 그래서 '살다' 와 '일광' 이
    # 같은 글에 없었으면 영영 못 잇는다. 벡터는 **간선이 없어도**
    # 가깝다는 것을 안다. 이것이 해시로는 못 하던 일이다.
    try:
        import vectors as _vc
        nodes = list((gmap.get("nodes") or {}))
        for s_ in starts:
            for nb, sim in _vc.near(s_, k=6, pool=nodes):
                out[nb] = max(out.get(nb, 0.0), HOP1 * float(sim))
    except Exception:
        pass

    # 1걸음 — 지도에서 바로 이어진 것
    first = []
    for s in starts:
        try:
            for nb, w in SM.neighbors(gmap, s, k=8):
                out[nb] = max(out.get(nb, 0.0), HOP1 * min(1.0, w))
                first.append(nb)
        except Exception:
            pass

    # 1걸음 — 끌리는 쪽 (중력). 이어짐과 다른 것을 잡는다.
    if mass:
        try:
            import word_gravity as WG
            for s in starts:
                for nb, p in WG.attracted(gmap, mass, s, k=6):
                    out[nb] = max(out.get(nb, 0.0), HOP1 * min(1.0, p / 3.0))
                    first.append(nb)
        except Exception:
            pass

    # 2걸음 — 한 다리 건넌 것 (약하게)
    for a in first[:20]:
        try:
            for nb, w in SM.neighbors(gmap, a, k=4):
                if nb in out:
                    continue
                out[nb] = HOP2 * min(1.0, w)
        except Exception:
            pass

    # 같은 갈래에 든 것
    if clusters:
        for c in clusters:
            members = c.get("members") or []
            if not any(s in members for s in starts):
                continue
            for m in members[:14]:
                out[m] = max(out.get(m, 0.0), SAME_CLUSTER)

    # 너무 퍼지면 아무거나 걸린다
    if len(out) > MAX_SPREAD:
        out = dict(sorted(out.items(), key=lambda kv: -kv[1])[:MAX_SPREAD])
    return out


def boost(text: str, spread_map: dict) -> float:
    """
    이 사실이 번진 자리에 얼마나 걸쳐 있나. 곱할 값으로 쓴다.

    1.0 이면 아무 상관 없음, 클수록 가깝다.
    **기존 점수를 갈아치우지 않고 곱한다** — 지도가 성글 때
    오히려 나빠지는 것을 막기 위해서다.
    """
    if not spread_map or not text:
        return 1.0
    hit = 0.0
    for w in set(TOKEN.findall(text)):
        v = spread_map.get(w)
        if v:
            hit += v
    if hit <= 0:
        return 1.0
    return round(1.0 + min(2.5, hit), 3)


def why(text: str, spread_map: dict, k: int = 3) -> list:
    """무엇 때문에 끌려 올라왔나 — 기록에 남길 까닭."""
    got = [(spread_map.get(w, 0.0), w)
           for w in set(TOKEN.findall(text or ""))
           if spread_map.get(w)]
    got.sort(reverse=True)
    return [w for _, w in got[:k]]


def load_map(sb):
    """지도와 갈래, 그리고 질량을 한 번에."""
    try:
        import semantic_map as SM
        gmap, cls = SM.load(sb)
    except Exception:
        return None, None, None
    mass = None
    try:
        import word_gravity as WG
        mass = WG.masses(gmap)
    except Exception:
        pass
    return gmap, cls, mass
