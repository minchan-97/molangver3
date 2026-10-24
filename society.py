"""
society.py — **이웃끼리의 사회.** LLM 없이 돈다.

왜 필요했나
  지금까지 피우피우·슈야·토야·미피·핀코는 **몰랑이하고만** 말했다.
  슈야와 토야가 같은 방에 있어도 둘 사이엔 아무 일도 없었다.
  그건 사회가 아니라 **몰랑이를 축으로 한 바퀴살**이다.

  그런데 서로 말하게 하려고 매번 LLM 을 부르면, 다섯이면 쌍이 열이라
  비용이 몇 배가 된다. 그래서 **만나는 것과 말하는 것을 나눈다.**

    stir(15분)    마주치고, 관심이 옮고, 들은 것이 전해지고, 사이가 쌓인다
                  → **LLM 없음**
    hourly        그날 가장 짙은 만남 하나만 실제 말로 옮긴다
    nightly       다 같이 무엇을 만들지 정한다 (투표)

무엇을 주고받나 (LLM 없이)
  관심   함께 있던 상대의 관심이 조금 옮는다
  소문   "슈야가 바다 얘기를 하더라" 가 기억에 남는다
  사이   bonds 에 만남이 쌓인다

  셋 다 숫자와 틀이라 LLM 이 필요 없다. 그런데도 **결이 번진다.**
  한 사람이 바다에 꽂히면 그게 마을을 돈다.

무엇을 안 하나
  여기서 생긴 말은 **몰랑이 사실로 쌓지 않는다.**
  다섯이 서로 지어낸 말을 주고받으면 순환 출처가 생긴다.
  그들의 기억에만 남고, 몰랑이는 직접 들은 것만 안다.
"""
from __future__ import annotations
import random
import re
import time

BLEED = 0.12          # 만났을 때 상대 관심이 옮는 정도
MAX_BLEED = 3         # 한 번에 옮는 낱말 수
RUMOR_KEEP = 8        # 각자 간직하는 소문 수
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")


def blank() -> dict:
    return {"meets": [], "rumors": {}, "log": []}


def load(sb) -> dict:
    try:
        rows = (sb.table("molang_society").select("data")
                .eq("id", 1).limit(1).execute().data) or []
        if rows and rows[0].get("data"):
            d = rows[0]["data"]
            for k, v in blank().items():
                d.setdefault(k, v)
            return d
    except Exception:
        pass
    return blank()


def save(sb, s: dict) -> bool:
    try:
        s["meets"] = (s.get("meets") or [])[-120:]
        s["log"] = (s.get("log") or [])[-60:]
        sb.table("molang_society").upsert(
            {"id": 1, "data": s}, on_conflict="id").execute()
        return True
    except Exception:
        return False


def _top(interests: dict, k: int = 5) -> list:
    return [w for w, _ in sorted((interests or {}).items(),
                                 key=lambda kv: -kv[1])[:k]]


def tick(sb, s: dict, who: dict, rng=None, log=print) -> dict:
    """
    **같은 자리에 있는 이들끼리 주고받는다.** LLM 없이.

    who: villagers.load() 가 준 것 {이름: {where, interests, memory, …}}
    """
    rng = rng or random.Random(time.time_ns())
    byplace = {}
    for name, v in (who or {}).items():
        p = v.get("where")
        if p:
            byplace.setdefault(p, []).append(name)

    met = []
    for place, names in byplace.items():
        if len(names) < 2:
            continue
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                met.append(_exchange(s, who, a, b, place, rng))

    # 사이는 bonds 에 쌓는다 (몰랑이와의 사이와 같은 표를 쓴다)
    if met:
        try:
            import bonds as _bd
            _b = _bd.load(sb)
            for m in met:
                _bd.remember(_b, m["a"], m["b"], m.get("topic") or "",
                             place=m.get("place") or "")
            _bd.save(sb, _b)
        except Exception:
            pass
        for m in met:
            s.setdefault("meets", []).append({**m, "at": time.time()})
        if log:
            log(f"  🏘️ 이웃끼리 마주침 {len(met)}번: "
                + ", ".join(f"{m['a']}·{m['b']}@{m['place']}"
                            for m in met[:3]))
    return {"met": len(met), "pairs": [(m["a"], m["b"]) for m in met]}


def _exchange(s: dict, who: dict, a: str, b: str, place: str, rng) -> dict:
    """
    둘이 주고받는 것.
      관심이 옮고, 소문이 전해진다. 말은 하지 않는다.
    """
    va, vb = who.get(a) or {}, who.get(b) or {}
    ta, tb = _top(va.get("interests") or {}), _top(vb.get("interests") or {})

    # 관심이 옮는다 — 상대가 꽂혀 있는 것 몇 개
    topic = None
    for src, dst, words in ((a, b, ta), (b, a, tb)):
        d = who.get(dst) or {}
        it = d.setdefault("interests", {})
        for w in words[:MAX_BLEED]:
            if rng.random() < 0.6:
                it[w] = min(5.0, float(it.get(w, 0.0)) + BLEED)
                topic = topic or w

    # 소문 — 들은 것이 남는다 (지어낸 말이 아니라 '누가 무엇에 꽂혔나')
    if topic:
        for src, dst in ((a, b), (b, a)):
            r = s.setdefault("rumors", {}).setdefault(dst, [])
            line = f"{src}가 요즘 {topic} 얘기를 하더라"
            if line not in r:
                r.append(line)
            s["rumors"][dst] = r[-RUMOR_KEEP:]

    return {"a": a, "b": b, "place": place, "topic": topic}


def hottest(s: dict, within_h: int = 6) -> dict | None:
    """
    **그날 가장 짙은 만남.** hourly 에서 이것 하나만 실제 말로 옮긴다.
    자주 마주친 짝이, 또렷한 화제를 가진 쪽이 뽑힌다.
    """
    now = time.time()
    rows = [m for m in (s.get("meets") or [])
            if now - float(m.get("at") or 0) < within_h * 3600
            and m.get("topic")]
    if not rows:
        return None
    count = {}
    for m in rows:
        key = tuple(sorted([m["a"], m["b"]]))
        count[key] = count.get(key, 0) + 1
    best = max(rows, key=lambda m: count.get(
        tuple(sorted([m["a"], m["b"]])), 0))
    return {**best, "times": count.get(
        tuple(sorted([best["a"], best["b"]])), 0)}


def rumors_of(s: dict, name: str) -> list:
    return list((s.get("rumors") or {}).get(name) or [])


def describe(s: dict) -> str:
    n = len(s.get("meets") or [])
    r = sum(len(v) for v in (s.get("rumors") or {}).values())
    return f"[사회] 마주침 {n}번 · 떠도는 말 {r}개"
