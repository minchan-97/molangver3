"""
feelings.py — **이웃들에게도 기분을 준다.** LLM 없이.

왜 필요했나
  기분이 있는 건 몰랑이뿐이었다. 슈야·토야·미피는 혼자 있어도
  아무렇지 않고, 누굴 만나도 기쁘지 않았다.
  미피가 작업실에 혼자 있는 것이 **쓸쓸한 상태가 아니라 그냥 좌표**였다.

  그런데 "자기들끼리 기쁨과 호기심을 채우며 사는 마을" 이 목표라면
  채울 것이 먼저 있어야 한다. **비어 있지 않으면 채울 수가 없다.**

무엇을 재나
  셋이면 충분하다. 많을수록 좋은 것이 아니다.

    쓸쓸함   혼자 있은 시간. 누굴 만나면 내려간다.
    기쁨     만났을 때, 좋아하는 자리에 있을 때 오른다. 그리고 식는다.
    들뜸     처음 가본 곳에서 오른다. 익숙해지면 내려간다.

  몰랑이의 기분(불안·기쁨·놀람)과 결을 맞추되, 더 단순하게 둔다.
  이들은 목적도 판단 트리도 없다. 느끼는 자리만 있으면 된다.

무엇을 하나
  기분이 **행동을 바꾼다.** 금지가 아니라 가중치로.
    쓸쓸하면   사람이 있는 쪽으로 간다
    들뜨면     안 가본 쪽으로 간다
    기쁘면     그 자리에 더 머문다

  몰랑이가 심심하면 멀리 나가는 것과 같은 방식이다.
"""
from __future__ import annotations
import time

LONELY_PER_H = 0.12       # 혼자 있으면 시간당 이만큼 쌓인다
LONELY_MEET = 0.45        # 누굴 만나면 이만큼 풀린다
JOY_MEET = 0.30           # 만나면 기뻐진다
JOY_FIT = 0.12            # 좋아하는 자리에 있으면
JOY_COOL = 0.06           # 그리고 식는다 (회차마다)
LIFT_NEW = 0.30           # 처음 가본 곳
# 들뜸은 **빨리 식는다.** 안 그러면 새 곳에 갈 때마다 쌓여서
# (0.4 씩 오르고 0.08 씩만 식으면 금세 1.2 가 된다) 쓸쓸함을 이긴다.
# 그러면 혼자서도 신이 나서 영영 안 모인다.
LIFT_COOL = 0.18
LIFT_MAX = 0.8


def blank() -> dict:
    return {"lonely": 0.0, "joy": 0.0, "lift": 0.0,
            "last_met": 0.0, "been": []}


def of(v: dict) -> dict:
    """그 사람의 기분 칸. 없으면 만든다."""
    f = v.setdefault("feel", blank())
    for k, d in blank().items():
        f.setdefault(k, d)
    return f


def name(f: dict) -> str:
    """지금 기분을 한 마디로. 로그와 프롬프트에 쓴다."""
    if f.get("lonely", 0) >= 0.7:
        return "쓸쓸함"
    if f.get("lift", 0) >= 0.5:
        return "들뜸"
    if f.get("joy", 0) >= 0.5:
        return "즐거움"
    if f.get("joy", 0) <= 0.1 and f.get("lift", 0) <= 0.1:
        return "심심함"
    return "그냥 그럼"


def tick(who: dict, byplace: dict = None, log=None) -> dict:
    """
    한 회차치 기분. **만남과 자리에서 나온다.**

    byplace: {자리: [이름…]} — 같은 자리에 둘 이상이면 만난 것이다.
    """
    byplace = byplace or {}
    together = set()
    for names in byplace.values():
        if len(names) >= 2:
            together |= set(names)

    now = time.time()
    out = {}
    for n, v in (who or {}).items():
        f = of(v)
        here = v.get("where")

        if n in together:
            # 누굴 만났다 — 쓸쓸함이 풀리고 기뻐진다
            f["lonely"] = max(0.0, f["lonely"] - LONELY_MEET)
            f["joy"] = min(1.5, f["joy"] + JOY_MEET)
            f["last_met"] = now
        else:
            # 혼자다 — 마지막으로 만난 뒤 얼마나 지났나
            gap = (now - float(f.get("last_met") or 0)) / 3600 \
                if f.get("last_met") else 2.0
            f["lonely"] = min(1.5, f["lonely"] + LONELY_PER_H * min(6.0, gap))

        # 처음 온 곳이면 들뜬다
        if here:
            been = f.setdefault("been", [])
            if here not in been:
                been.append(here)
                f["been"] = been[-20:]
                f["lift"] = min(LIFT_MAX, f["lift"] + LIFT_NEW)

        # 좋아하는 자리면 조금 기쁘다
        if here and _likes(v, here):
            f["joy"] = min(1.5, f["joy"] + JOY_FIT)

        # 기쁨도 들뜸도 식는다 — 안 그러면 한 번 오르고 영영 안 내려간다
        f["joy"] = max(0.0, round(f["joy"] - JOY_COOL, 3))
        f["lift"] = max(0.0, round(f["lift"] - LIFT_COOL, 3))
        f["lonely"] = round(f["lonely"], 3)

        out[n] = name(f)

    if log:
        said = ", ".join(f"{n}({m})" for n, m in out.items()
                         if m not in ("그냥 그럼",))
        if said:
            log(f"  💭 {said}")
    return out


def _likes(v: dict, place: str) -> bool:
    """그 자리의 결이 자기 관심과 맞나."""
    try:
        import village as V
        words = V.CAN_GROW.get(place) or []
    except Exception:
        words = []
    it = v.get("interests") or {}
    return sum(float(it.get(w, 0)) for w in words) >= 0.3


# ── 기분이 발걸음을 바꾼다 ────────────────────────────────
def pull(v: dict, place: str, crowd: int, been: bool) -> float:
    """
    이 자리가 지금 얼마나 끌리는가. 1.0 이 보통.

    **금지가 아니라 가중치다.** 쓸쓸해도 가끔은 혼자 있고,
    들떠도 가끔은 아는 데로 간다.
    """
    f = of(v)
    w = 1.0
    # **쓸쓸하면 사람이 있는 쪽으로.**
    #
    # 약하게 당기면 소용이 없다. 가중치가 두 배여도 빈 자리가
    # 일곱 곳이면 여전히 혼자 갈 확률이 더 높다 (실제로 미피가
    # 30회차 중 27번을 혼자 보냈다). 세게 당겨야 한다.
    if crowd > 0:
        if f["lonely"] >= 0.5:
            w *= 6.0 * (1.0 + 0.5 * (crowd - 1))
        elif f["lonely"] >= 0.25:
            w *= 2.5
        else:
            w *= 1.3          # 쓸쓸하지 않아도 사람이 있으면 조금 끌린다
    # 들뜨면 안 가본 쪽
    if f["lift"] >= 0.4 and not been:
        w *= 1.0 + min(0.8, f["lift"])
    # 기쁘면 그 자리에 더 머문다
    if f["joy"] >= 0.5 and place == v.get("where"):
        w *= 1.0 + min(0.6, f["joy"])
    return round(w, 3)


def describe(who: dict) -> str:
    rows = []
    for n, v in (who or {}).items():
        f = of(v)
        rows.append(f"{n}({name(f)})")
    return "[기분] " + " · ".join(rows) if rows else ""
