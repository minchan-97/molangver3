"""
purpose_drive.py — 승인된 목적이 실제로 행동을 바꾼다.

무엇이 빠져 있었나
  목적은 제안되고 승인되고 저장까지 됐지만, **아무 데서도 읽지 않았다.**
  load_subs 가 쓰이는 곳은 사이드바 목록과 중복 제안 방지 두 곳뿐이었다.
  그래서 파스타·인공지능·바다·자기 자신 네 목적을 승인해도 몰랑이의
  탐색과 사고는 하나도 달라지지 않았다. 기록만 남는 목적이었다.

무엇을 잇나 (넷)
  1. 주제 고르기   목적과 가까운 주제에 가중치
  2. 검색어 넓히기  목적이 문맥으로 들어간다
  3. 대화          "요즘 알고 싶은 것"으로 프롬프트에
  4. 사고 깊어지기  목적에 걸린 주제의 근거는 더 세게 쌓인다
                   (목적이 있으면 그 분야 사고가 먼저 깊어져야 한다)

원칙
  목적은 **가중치**이지 금지가 아니다. 자유 탐색 몫은 그대로 둔다.
  목적만 좇으면 새것을 못 만나고, 그건 이 존재의 핵심 목적과 어긋난다.
"""
from __future__ import annotations
import re

PULL = 0.55              # 목적과 가까운 주제가 받는 가산 (최대)
FEED_BOOST = 1.6         # 목적 주제의 근거에 실리는 무게
DEEPEN_DISCOUNT = 2      # 목적 분야는 이만큼 적은 근거로도 깊어진다
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")


def _vec(text: str):
    from organism.embedder import hashed_embedding
    return hashed_embedding(text or "", dim=64)


def load(sb) -> list:
    """승인된 하위 목적 (핵심 목적은 따로)."""
    try:
        import purpose_growth
        return purpose_growth.load_subs(sb) or []
    except Exception:
        return []


def words(subs: list) -> set:
    out = set()
    for s in subs:
        out |= set(TOKEN.findall(s.get("purpose") or ""))
        t = s.get("from_topic")
        if t:
            out.add(t)
    try:
        from organism.curiosity import _is_topic_like, strip_josa, canon_name
        out = {canon_name(strip_josa(w)) for w in out}
        out = {w for w in out if _is_topic_like(w)}
    except Exception:
        pass
    return out


def affinity(subs: list, topic: str) -> float:
    """
    이 주제가 지금 품은 목적들과 얼마나 가까운가. 0~1.
    낱말이 직접 겹치면 확실히, 아니면 임베딩 거리로.
    """
    if not subs or not topic:
        return 0.0
    w = words(subs)
    if topic in w:
        return 1.0
    tv = _vec(topic)
    best = 0.0
    for s in subs:
        sim = float(tv @ _vec(s.get("purpose") or ""))
        best = max(best, sim)
    # 낱말 겹침 보너스
    tw = set(TOKEN.findall(topic))
    if tw & w:
        best = max(best, 0.6)
    return round(max(0.0, min(1.0, best)), 3)


def weight_topics(subs: list, scores: dict) -> dict:
    """
    주제 점수에 목적을 실는다. **덮어쓰지 않고 얹는다** —
    자유 탐색 몫이 사라지면 새것을 못 만난다.
    """
    if not subs:
        return scores
    out = {}
    for t, s in (scores or {}).items():
        out[t] = s * (1.0 + PULL * affinity(subs, t))
    return out


def query_context(subs: list, topic: str, limit=2) -> str:
    """검색어를 넓힐 때 문맥으로 들어갈 한 줄."""
    if not subs:
        return ""
    near = sorted(subs, key=lambda s: -affinity([s], topic))[:limit]
    near = [s for s in near if affinity([s], topic) > 0.25]
    if not near:
        return ""
    return "요즘 알고 싶은 것: " + " / ".join(
        (s.get("purpose") or "")[:40] for s in near)


def chat_context(subs: list, limit=3) -> str:
    """대화 프롬프트에 들어갈 줄."""
    if not subs:
        return ""
    body = "\n".join(f"  - {(s.get('purpose') or '')[:50]}" for s in subs[:limit])
    return ("[요즘 내가 알고 싶은 것]\n" + body +
            "\n(묻지 않았는데 굳이 꺼내지는 말고, 이야기가 그쪽으로 가면 "
            "더 궁금해한다)\n")


def feed_weight(subs: list, topic: str) -> float:
    """
    이 주제의 근거를 얼마나 무겁게 쌓을까.
    목적에 걸린 분야는 더 세게 — 그래야 그쪽 사고가 먼저 깊어진다.
    """
    a = affinity(subs, topic)
    return 1.0 + (FEED_BOOST - 1.0) * a


def deepen_threshold(subs: list, tid: str, base: int) -> int:
    """
    목적과 이어진 트리는 **더 적은 근거로도** 깊어진다.
    (관심이 큰 분야의 사고가 먼저 자라는 건 자연스럽다)
    """
    if not subs:
        return base
    a = affinity(subs, tid.replace("_", " "))
    if a < 0.3:
        return base
    return max(2, base - DEEPEN_DISCOUNT)


def status(sb) -> dict:
    subs = load(sb)
    return {"count": len(subs),
            "purposes": [(s.get("purpose") or "")[:40] for s in subs],
            "words": sorted(words(subs))[:12]}
