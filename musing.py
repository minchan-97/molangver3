"""
musing.py — 몰랑이의 '조용한 생각'.

사람도 시도 때도 없이 생각하지만 그걸 매번 문장으로 만들지는 않는다.
여기서도 마찬가지로 나눈다.

  조용한 생각 (LLM 없음, 비용 0)   — 이 파일. 자주 돌려도 된다.
  말이 되는 생각 (LLM 호출)        — 회고·먼저 말 걸기. 하루 한두 번.

생각의 종류 다섯
  recall    지난 대화를 되짚는다 — 무엇이 자주 나왔나, 무엇이 끊겼나
  wonder    다음에 무엇을 알아볼까 — 관심은 큰데 아직 안 파본 것
  connect   따로 알던 것을 잇는다 — 같은 낱말이 걸친 관심사끼리 묶기
  wish      더 하고 싶은 것 — 자주 나왔는데 근거가 얇은 자리
  settle    정리한다 — 오래된 관심 옅어지기, 부스러기 버리기

모든 종류는 '생각의 흔적'만 남긴다 (state.musings).
그 흔적이 쌓이면 밤에 회고가 그걸 재료로 문장을 만든다.
즉 말은 생각의 요약이지, 생각 그 자체가 아니다.
"""
from __future__ import annotations
import random
import re
import time

KINDS = ["recall", "wonder", "connect", "wish", "settle"]
MAX_TRACE = 200          # 흔적은 이만큼만 (오래된 것부터 버림)
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")


def _topics(state, n=12):
    return [t for t, _ in sorted((state.interests or {}).items(),
                                 key=lambda kv: -kv[1])[:n]]


def recall(state):
    """지난 대화·관측에서 자주 나온 것과 끊긴 것을 짚는다."""
    seen = list(getattr(state, "visited", {}) or {})
    hot = _topics(state, 5)
    cold = [t for t in hot if state.visited.get(t, 0) == 0]
    return {"kind": "recall", "hot": hot[:3], "untouched": cold[:3],
            "visited": len(seen)}


def wonder(state, rng=None):
    """다음에 무엇을 알아볼까 — 관심은 큰데 아직 덜 판 것."""
    rng = rng or random.Random()
    cand = [(t, state.interests[t] * state.novelty(t)) for t in _topics(state, 12)]
    cand.sort(key=lambda kv: -kv[1])
    pick = [t for t, _ in cand[:3]]
    return {"kind": "wonder", "next_maybe": pick,
            "why": "관심도 × 새로움이 높은 순"}


def connect(state):
    """따로 알던 관심사 중 낱말이 겹치는 것끼리 묶어 본다."""
    ts = _topics(state, 12)
    pairs = []
    for i in range(len(ts)):
        for j in range(i + 1, len(ts)):
            a, b = set(TOKEN.findall(ts[i])), set(TOKEN.findall(ts[j]))
            if a & b:
                pairs.append([ts[i], ts[j]])
    return {"kind": "connect", "linked": pairs[:3]}


def wish(state):
    """더 하고 싶은 것 — 관심은 있는데 관측이 얇은 자리."""
    counts = {}
    for o in (getattr(state, "observations", []) or []):
        t = o.get("topic") if isinstance(o, dict) else None
        if t:
            counts[t] = counts.get(t, 0) + 1
    thin = [t for t in _topics(state, 10) if counts.get(t, 0) <= 1]
    return {"kind": "wish", "want_more": thin[:3],
            "why": "관심은 있는데 아직 본 게 적음"}


def settle(state, decay=0.985, floor=0.02):
    """오래된 관심은 옅어지고, 부스러기는 버린다."""
    try:
        from organism.curiosity import _is_topic_like, strip_josa
    except Exception:
        def _is_topic_like(t):
            return 2 <= len(t) <= 12

        def strip_josa(t):
            return t

    # 조사만 다른 관심사는 하나로 합친다 ('우주에' + '우주' → '우주')
    for t in list((state.interests or {}).keys()):
        base = strip_josa(t)
        if base != t and _is_topic_like(base):
            state.interests[base] = min(
                5.0, state.interests.get(base, 0.0) + state.interests.pop(t))

    dropped, faded = [], 0
    for t in list((state.interests or {}).keys()):
        # 띄어쓰기가 있어도 말투면 버린다 ('있어 파스타' 같은 붙은 조각)
        parts = [p for p in t.split() if p]
        if len(parts) > 1 and not all(_is_topic_like(p) for p in parts):
            state.interests.pop(t, None)
            dropped.append(t)
            continue
        if not _is_topic_like(t) and " " not in t:
            state.interests.pop(t, None)
            dropped.append(t)
            continue
        v = state.interests[t] * decay
        if v < floor:
            state.interests.pop(t, None)
            dropped.append(t)
        else:
            state.interests[t] = v
            faded += 1
    return {"kind": "settle", "faded": faded, "dropped": dropped[:5]}


def think(state, kinds=None, rng=None, log=print):
    """
    한 번의 조용한 생각. LLM 을 부르지 않는다.
    흔적을 state.musings 에 남기고, 그 요약을 돌려준다.
    """
    rng = rng or random.Random(time.time_ns())
    kinds = kinds or KINDS
    out = {}
    for k in kinds:
        try:
            out[k] = {"recall": recall, "wonder": wonder, "connect": connect,
                      "wish": wish, "settle": settle}[k](state)
        except Exception as e:
            out[k] = {"kind": k, "error": str(e)[:80]}

    trace = list(getattr(state, "musings", []) or [])
    trace.append({"at": time.time(), **{k: v for k, v in out.items()}})
    state.musings = trace[-MAX_TRACE:]
    log("  조용한 생각: " + " · ".join(
        f"{k}" for k in out if not out[k].get("error")))
    return out


def think_many(state, rounds=30, rng=None, log=print, stop_when_still=5):
    """
    한 번 깨어났을 때 여러 번 생각한다.

    왜 여러 번인가
      러너를 한 번 띄우는 데 2분이 든다. 실제 생각은 몇 밀리초다.
      그래서 깨어난 김에 여러 번 생각하는 쪽이 훨씬 싸다.

    왜 무한정은 아닌가
      같은 생각을 반복하면 의미가 없다. 관심 지형이 더 이상 변하지 않으면
      (연속 stop_when_still 회) 그만둔다. 생각이 멈출 줄 아는 것도 설계다.

    회차마다 종류를 조금씩 바꾼다 — 매번 다섯 가지를 다 하지는 않는다.
    사람도 어떤 때는 되짚기만, 어떤 때는 정리만 한다.
    """
    rng = rng or random.Random(time.time_ns())
    last = None
    still = 0
    done = 0
    for i in range(max(1, rounds)):
        # 이번엔 어떤 생각을 할까 (settle 은 가끔, 나머지는 자주)
        kinds = [k for k in ("recall", "wonder", "connect", "wish")
                 if rng.random() < 0.7] or ["wonder"]
        think(state, kinds=kinds, rng=rng, log=lambda *a: None)
        done += 1

        shape = tuple(sorted((t, round(v, 3))
                             for t, v in (state.interests or {}).items()))
        if shape == last:
            still += 1
            if still >= stop_when_still:
                break
        else:
            still = 0
            last = shape

    # 정리(망각)는 깨어날 때 한 번만. 생각할 때마다 걸면 몇 분 만에
    # 관심이 다 사라진다 — 망각은 시간의 함수지 생각 횟수의 함수가 아니다.
    tidy = settle(state)

    log(f"  조용한 생각 {done}회 · 관심사 {len(state.interests or {})}개"
        + (f" · 버린 부스러기 {len(tidy['dropped'])}개" if tidy["dropped"] else ""))
    return {"rounds": done, "stopped_early": done < rounds,
            "interests": len(state.interests or {}),
            "dropped": tidy["dropped"]}


def to_reflection_context(state, n=6) -> str:
    """밤에 회고(문장)를 쓸 때 재료로 주는 요약. 말은 생각의 요약이다."""
    trace = (getattr(state, "musings", []) or [])[-n:]
    if not trace:
        return ""
    lines = []
    for m in trace:
        w = (m.get("wonder") or {}).get("next_maybe") or []
        wi = (m.get("wish") or {}).get("want_more") or []
        c = (m.get("connect") or {}).get("linked") or []
        if w:
            lines.append("알아보고 싶던 것: " + ", ".join(w))
        if wi:
            lines.append("더 보고 싶던 것: " + ", ".join(wi))
        if c:
            lines.append("이어본 것: " + ", ".join("-".join(p) for p in c))
    return "\n".join(dict.fromkeys(lines))[:800]

