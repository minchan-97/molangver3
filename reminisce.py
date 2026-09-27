"""
reminisce.py — 문득 옛일이 떠오른다.

왜 필요한가
  지금 기억 꺼내기(recall)는 '질문과 가까운 것'을 뽑는다. 그건 대답을 위한
  기억이다. 그런데 사람은 아무도 묻지 않아도 옛일이 떠오르고, 그게 대화의
  시작이 된다. "그러고 보니 예전에 베네치아 얘기 했었지" 같은 것.

  그 결이 빠지면, 아는 게 많아져도 늘 최근 얘기만 하는 존재가 된다.

무엇이 떠오르나 (오래 안 꺼낸 것을 고른다 — recall 과 반대 방향)
  점수 = 묵은 정도 × 굳기 × 감정의 무게 × (연결 있으면 가산)

    묵은 정도   마지막으로 쓰인 지 오래일수록 높다
    굳기        확신일수록 (흐릿한 기억은 굳이 안 떠오른다)
    감정        여행·사람·처음 같은 말이 있으면 조금 더
    연결        지금 관심과 낱말이 겹치면 가산
                ("노래"에 마음이 가 있을 때 예전 음악 기억이 떠오르는 것)

무엇에 쓰나
  1) 먼저 말 걸기의 계기 — "그러고 보니 …"
  2) 호기심 주제 — 회상에서 나온 낱말을 탐색 주제로
     (베네치아 기억 → '곤돌라'를 찾아보게)
  3) 조용한 생각의 재료

떠오른 기억은 기록해서 **연달아 같은 것만 떠오르지 않게** 한다.
"""
from __future__ import annotations
import re
import time

WARM = ("여행", "처음", "함께", "친구", "가족", "바다", "노래", "선물",
        "기억", "추억", "그때", "어릴", "사진", "편지")
COOLDOWN_DAYS = 3          # 한 번 떠올린 기억은 며칠 쉬었다가
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")


def _age_days(f: dict) -> float:
    """마지막으로 쓰이거나 갱신된 지 며칠. 알 수 없으면 중간값."""
    for k in ("updated_at", "created_at"):
        v = f.get(k)
        if not v:
            continue
        try:
            from datetime import datetime, timezone
            t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            return max(0.0, (datetime.now(timezone.utc) - t).days)
        except Exception:
            continue
    return 7.0


def _warmth(text: str) -> float:
    return 1.0 + 0.25 * sum(1 for w in WARM if w in (text or ""))


def pick(facts: list[dict], interests: dict = None, recent_ids=(),
         n: int = 1) -> list[dict]:
    """떠올릴 기억 고르기. 오래 안 꺼낸 것 우선."""
    interests = interests or {}
    itok = set()
    for t in list(interests)[:10]:
        itok |= set(TOKEN.findall(t))

    scored = []
    for f in (facts or []):
        text = f.get("text") or ""
        if len(text) < 8 or f.get("id") in recent_ids:
            continue
        age = _age_days(f)
        if age < COOLDOWN_DAYS:
            continue                     # 최근 것은 회상이 아니다
        s = (f.get("strength") or 0.5)
        score = (1.0 + age / 7.0) * s * _warmth(text)
        if itok & set(TOKEN.findall(text)):
            score *= 1.6                 # 지금 관심과 이어지면 더 잘 떠오른다
        scored.append((score, f))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:n]]


def to_topic(fact: dict) -> str | None:
    """
    회상에서 탐색 주제를 뽑는다. 사실 문장 전체가 아니라 그 안의 명사 하나.
    ('사용자는 베네치아에서 곤돌라를 탔다' → '곤돌라')
    """
    try:
        from organism.curiosity import _is_topic_like, strip_josa, canon_name
    except Exception:
        return None
    words = [canon_name(strip_josa(w)) for w in TOKEN.findall(fact.get("text") or "")]
    # '들어보려고' 같은 말끝이 회상에서 새어 나가 관심이 됐다.
    # 주제 검사를 똑같이 거치게 한다.
    cand = [w for w in words
            if _is_topic_like(w) and w not in ("사용자",) and len(w) >= 2]
    if not cand:
        return None
    # 가장 긴 것이 아니라, 가장 '이름다운' 것을 고른다 (긴 활용형 배제)
    cand.sort(key=lambda w: (-len(w), w))
    for w in cand:
        if len(w) <= 6:
            return w
    return cand[-1]


def line(fact: dict) -> str:
    """회상 한 마디. 사실을 그대로 읊지 않고 떠올린 투로."""
    t = (fact.get("text") or "").rstrip(".")
    t = re.sub(r"^(사용자는|찬기는|그는)\s*", "", t)
    return f"그러고 보니, {t} … 그거 요즘은 어때?"


def remember_used(state, fact_ids):
    """떠올린 기억을 기록해 연달아 같은 것만 나오지 않게."""
    used = list(getattr(state, "reminisced", []) or [])
    used += [{"id": i, "at": time.time()} for i in fact_ids if i]
    state.reminisced = used[-50:]
    return state.reminisced


def recent_ids(state, days: int = COOLDOWN_DAYS) -> set:
    cut = time.time() - days * 86400
    return {u["id"] for u in (getattr(state, "reminisced", []) or [])
            if u.get("at", 0) > cut}
